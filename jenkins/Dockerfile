FROM jenkins/jenkins:lts-jdk17

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash coreutils findutils libgl1 procps python3 unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=jenkins:jenkins scripts /opt/harmony-build/scripts
COPY --chown=jenkins:jenkins jenkins/ref /usr/share/jenkins/ref

RUN chmod +x /opt/harmony-build/scripts/build_harmony_zip.sh

ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false"
ENV JENKINS_OPTS="--httpPort=8080"
ENV JOBS_DIR=/data/jobs
ENV TOOLS_DIR=/opt/harmony/command-line-tools
ENV BUILD_TIMEOUT_SECONDS=1200

USER jenkins
