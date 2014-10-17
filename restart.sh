#!/bin/bash

cp  /Users/peterbryzgalov/work/docker-registry-driver-git/docker_registry/drivers/gitdriver.py /Users/peterbryzgalov/work/docker-registry/docker_registry/drivers/
rm -rf /private/tmp/gitrepo 
rm -rf /private/tmp/gitregistry 
rm -rf /private/tmp/docker-registry.db
./registry-start
