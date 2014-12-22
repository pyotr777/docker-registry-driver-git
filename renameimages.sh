#!/bin/bash

old_addr=$1
new_addr=$2
version="1.0"

echo "Script for renaming docker images using \"docker tag\" command."
echo "Version $version"

if [ -z "$old_addr" ] || [ -z "$new_addr" ]
then    
    echo "Usage: renameimages.sh old_address new_addres."
    exit 0;
fi

images_old=( $(docker images | grep $RA | awk '{ print $1 ":" $2 }') )

for image in ${images_old[@]} 
do
    image_new=${image//$old_addr/$new_addr}
    echo "$image -> $image_new"
    docker tag $image $image_new
    docker rmi $image
done