# ============================================================
# openGauss 7.0 database image with the openblas runtime dependency.
#
# The official image is missing libopenblas.so.0, which prevents gaussdb
# from starting (validated during v3.3.0 M0). This derived image adds it.
#
# Build:
#   docker build -t pollybird/opengauss:7.0.0 docker/opengauss
#
# Optional build arg (local mirror / offline registry):
#   BASE_IMAGE=<mirror>/opengauss/opengauss:7.0.0-RC3.B025-openEuler22.03
# ============================================================
ARG BASE_IMAGE=opengauss/opengauss:7.0.0-RC3.B025-openEuler22.03
FROM ${BASE_IMAGE}

RUN dnf install -y openblas \
    && dnf clean all
