#!/bin/bash

image_path="$1"

echo "Uploading $image_path to cometa"

scp -3 "$image_path" cometa:/var/www/media/images/
