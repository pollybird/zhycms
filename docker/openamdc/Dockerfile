# ============================================================
# pollybird/openamdc — openAMDC 1.0.0 image
#
# Build:
#   docker build -t pollybird/openamdc:1.0.0 docker/openamdc
#
# Multi-arch build (x86_64 + aarch64, needs buildx + QEMU binfmt):
#   docker buildx build --platform linux/amd64,linux/arm64 \
#     -t pollybird/openamdc:1.0.0 --push docker/openamdc
#   aarch64 在 x86_64 主机上通过 QEMU 模拟编译，耗时会明显长于本机构建。
#
# Optional build args:
#   BASE_IMAGE=<registry-mirror>/openeuler/openeuler:24.03-lts-sp1
#   OPENAMDC_REF=<commit>
#
# Notes:
# - RocksDB is statically linked, so the first build is slow (tens of minutes).
# - Runtime only needs libstdc++ / snappy / zlib; no compiler toolchain.
# - Upstream commit is pinned for reproducible delivery.
# ============================================================
ARG BASE_IMAGE=openeuler/openeuler:24.03-lts-sp1

# ---- Stage 1: builder ----
FROM ${BASE_IMAGE} AS builder

ARG OPENAMDC_REPO=https://atomgit.com/openeuler/openAMDC.git
ARG OPENAMDC_REF=6758505d722a7efa0fd64dec5164e19885942f87
# 交叉架构（QEMU 模拟）构建时建议限制并发，避免内存不足。
ARG MAKE_JOBS=

RUN dnf install -y \
      gcc gcc-c++ make binutils glibc-devel \
      openssl-devel snappy-devel zlib-devel \
      git tar \
    && dnf clean all

WORKDIR /src
RUN git clone ${OPENAMDC_REPO} /src \
    && git checkout ${OPENAMDC_REF} \
    && make -j"${MAKE_JOBS:-$(nproc)}"

# ---- Stage 2: runtime ----
FROM ${BASE_IMAGE}

RUN dnf install -y libstdc++ snappy zlib shadow \
    && dnf clean all \
    && useradd -r -u 999 -M -d /data -s /sbin/nologin openamdc \
    && mkdir -p /data /etc/openamdc \
    && chown -R 999:999 /data /etc/openamdc

COPY --from=builder /src/src/openamdc-server /src/src/openamdc-cli \
     /src/src/openamdc-benchmark /usr/local/bin/
COPY --from=builder /src/LICENSE /usr/share/licenses/openamdc/LICENSE
COPY openamdc.conf /etc/openamdc/openamdc.conf
COPY entrypoint.sh /usr/local/bin/openamdc-entrypoint.sh

RUN chmod 0755 /usr/local/bin/openamdc-entrypoint.sh \
    && chown 999:999 /etc/openamdc/openamdc.conf

WORKDIR /data
USER 999
EXPOSE 6379

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD openamdc-cli -p 6379 ping || exit 1

ENTRYPOINT ["/usr/local/bin/openamdc-entrypoint.sh"]
CMD ["/etc/openamdc/openamdc.conf"]
