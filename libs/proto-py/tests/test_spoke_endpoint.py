from concurrent import futures

import grpc
import pytest
from google.protobuf import empty_pb2

from janus_proto import (
    HealthState,
    Payload,
    ResponseStatus,
    SemanticRequest,
    SemanticResponse,
    helpers,
)
from janus_proto.v1 import spoke_pb2, spoke_pb2_grpc

CALL_TIMEOUT_S = 10
PARTIAL_COUNT = 3


class EchoSpoke(spoke_pb2_grpc.SpokeEndpointServicer):
    def Invoke(self, request, context):
        yield helpers.progress_event(request, 0, "starting")
        for index in range(PARTIAL_COUNT):
            yield helpers.partial_event(request, index + 1, f"chunk-{index}")
        response = SemanticResponse(
            status=ResponseStatus.SUCCEEDED,
            output=Payload(text=request.input.text, content_type="text/plain"),
        )
        yield helpers.terminal_event(request, response, seq=PARTIAL_COUNT + 1)

    def Health(self, request, context):
        return spoke_pb2.HealthReport(state=HealthState.HEALTHY)


@pytest.fixture
def stub():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    spoke_pb2_grpc.add_SpokeEndpointServicer_to_server(EchoSpoke(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    yield spoke_pb2_grpc.SpokeEndpointStub(channel)
    channel.close()
    server.stop(grace=None)


def build_request() -> SemanticRequest:
    return SemanticRequest(
        request_id=helpers.new_request_id(),
        capability_id="reasoning.complete",
        session_id="sess",
        input=Payload(text="hola"),
    )


def test_should_stream_events_in_order_until_terminal(stub):
    events = list(stub.Invoke(build_request(), timeout=CALL_TIMEOUT_S))

    assert [event.seq for event in events] == list(range(PARTIAL_COUNT + 2))
    assert [helpers.is_terminal(event) for event in events] == [False] * (PARTIAL_COUNT + 1) + [
        True
    ]


def test_should_carry_request_identity_on_every_streamed_event(stub):
    request = build_request()

    events = list(stub.Invoke(request, timeout=CALL_TIMEOUT_S))

    assert {event.request_id for event in events} == {request.request_id}
    assert {event.session_id for event in events} == {"sess"}


def test_should_deliver_the_terminal_response_over_the_wire(stub):
    events = list(stub.Invoke(build_request(), timeout=CALL_TIMEOUT_S))

    terminal = events[-1]
    assert terminal.response.status == ResponseStatus.SUCCEEDED
    assert terminal.response.output.text == "hola"


def test_should_report_health_over_the_wire(stub):
    report = stub.Health(empty_pb2.Empty(), timeout=CALL_TIMEOUT_S)

    assert report.state == HealthState.HEALTHY


def test_should_use_the_versioned_wire_name():
    service = spoke_pb2.DESCRIPTOR.services_by_name["SpokeEndpoint"]

    assert service.full_name == "janus_proto.v1.SpokeEndpoint"
    assert sorted(method.name for method in service.methods) == ["Health", "Invoke"]
