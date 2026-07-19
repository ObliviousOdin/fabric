# Keep only rules that are required by reflective runtime behavior.
# Kotlin serialization models in this app use explicit serializers and do not
# require broad package-level keeps. R8's optimized defaults handle OkHttp and
# Compose metadata.
