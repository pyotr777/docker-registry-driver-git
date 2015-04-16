FROM registry
RUN apt-get update
RUN apt-get install -y git
RUN apt-get install -y python-tk
RUN pip install docker-registry-driver-git
ADD https://raw.githubusercontent.com/pyotr777/docker-registry-gitdriver-config/master/config.yml /docker-registry/config/config.yml
ENV DOCKER_REGISTRY_CONFIG /docker-registry/config/config.yml
ENV SETTINGS_FLAVOR dev

EXPOSE 5000

CMD ["docker-registry"]
