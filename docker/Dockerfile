# Ubuntu 24.04
# https://hub.docker.com/layers/library/ubuntu/24.04/images
FROM ubuntu@sha256:c35e29c9450151419d9448b0fd75374fec4fff364a27f176fb458d472dfc9e54

# Pin apt packages date.
# Ubuntu snapshots requires installing the latest ca-certificates package.
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
RUN echo 'APT::Snapshot "20260101T000000Z";' > /etc/apt/apt.conf.d/50snapshot

RUN apt-get update \
&& DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get install --no-install-recommends -y \
  # Required to build LLVM and AOSP.
  git \
  libssl-dev \
  make \
  patch \
  pkg-config \
  python3 \
  python3-pip \
  repo \
  rsync \
  ssh \
  unzip \
  xz-utils \
  zip \
  # Required by android-build buildbot.
  tzdata \
  # Necessary to test 32-bit runtimes.
  gcc-multilib \
  libc6-dev-i386-cross \
&& rm -rf /var/lib/apt/lists/*

# Install TensorFlow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --break-system-packages --require-hashes -r /tmp/requirements.txt \
&& rm -rf /root/.cache/pip /tmp/requirements.txt
ENV TENSORFLOW_INSTALL=/usr/local/lib/python3.12/dist-packages/tensorflow

# Set up git user identity, as required by repo
RUN printf '[user]\n  name = Builder\n  email = android-llvm+build@google.com' > /etc/gitconfig
