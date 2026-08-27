#!/bin/sh

# Create data folder as current user, otherwise Docker creates it as root
mkdir -p data

# Run the container as the current user to avoid creating files as root
DOCKER_USER="$(id -u):$(id -g)" docker-compose "$@"
