from hypothesis import HealthCheck, settings

settings.register_profile(
    "morphix",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("morphix")
