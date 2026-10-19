# SDSC S3 Mount Strategy for ollama-k8s

SDSC has such slow disk read/write speeds that it cannot be used for loading LLMs into memory. As a work around, we are mounting an S3 bucket with the model files, and loading models from the S3 bucket.

- `mount-s3` (S3FS) is used to mount the bucket.
- The pull-models job pulls models to a temporary directory and then copies over to the bucket. This is because the ollama pull process requires some POSIX commands that aren't supported by S3.

The following is how to setup the worker node to automatically mount the s3 bucket

### 1. Install mount-s3

[Install mount-s3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mountpoint-installation.html)

```
sudo dnf install mount-s3
sudo apt install https://s3.amazonaws.com/mountpoint-s3-release/latest/x86_64/mount-s3.deb
```

### 2. Test to make sure you can mount

Create a IAM service account in AWS that only has read/write access to the S3 bucket you'll be using. Create an access key for that IAM account and save to `~/.aws/credentials`

```toml
[default]
aws_access_key_id = A...
aws_secret_access_key = N...
aws_region = us-west-2
```

You should now be able to mount the s3 bucket

```bash
mount-s3 resilient-ollama-kubernetes-s3 $HOME/ollama-models --allow-delete --allow-overwrite
```

Create and delete some files to test. You can test speeds using `dd`.

```bash
umount ~/ollama-models
```

### 3. Mount the s3 bucket on boot

Add to `/etc/fstab` for persistent mounting at boot:

```
# /etc/fstab entry
s3://resilient-ollama-kubernetes-s3/ /home/ubuntu/ollama-models mount-s3 _netdev,nosuid,nodev,nofail,rw,allow-delete,allow-overwrite,uid=1000,gid=1000,allow-other 0 0
```

Then you need to make sure the root user has your aws credentials.

```bash
sudo mkdir /root/.aws
sudo cp ~/.aws/credentials /root/.aws/credentials
sudo systemctl daemon-reload
sudo mount -a
```

Now the S3 bucket should be mounted to `~/ollama-models`. You should also be able to reboot and see the bucket automatically mounted.

### Final Notes

You will need to create a snapshot of the worker node once this is done so as nodes spin up they use this precreated image.
