class BiometricsError(Exception):
    """Base error for janus_biometrics."""


class RemoteProviderNotAcknowledged(BiometricsError):
    def __init__(self, provider_ref: str) -> None:
        super().__init__(
            f"Provider '{provider_ref}' sends audio or image data off this device. "
            "Set biometrics.allow_remote = true and biometrics.remote_ack = true "
            "to acknowledge this before it can be registered."
        )
        self.provider_ref = provider_ref


class ModelMismatch(BiometricsError):
    def __init__(
        self, kind: str, profile: str, expected_model_id: str, actual_model_id: str
    ) -> None:
        super().__init__(
            f"Enrollment for {kind}/{profile} was created with model '{actual_model_id}', "
            f"but the configured provider uses '{expected_model_id}'. Re-enroll to continue."
        )
        self.kind = kind
        self.profile = profile
        self.expected_model_id = expected_model_id
        self.actual_model_id = actual_model_id


class EnrollmentError(BiometricsError):
    """Raised when enrollment cannot be completed (insufficient or invalid samples)."""


class KeyUnavailable(BiometricsError):
    """Raised when the template encryption key cannot be resolved."""


class SensorUnavailable(BiometricsError):
    def __init__(self, sensor_id: str, reason: str) -> None:
        super().__init__(f"Sensor '{sensor_id}' is unavailable: {reason}")
        self.sensor_id = sensor_id
        self.reason = reason


class ModelSourceError(BiometricsError):
    """Raised when a model cannot be obtained from its configured source."""
