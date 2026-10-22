# SDSC Scaling Compute Instances

You will need to create an application credential in openstack with:
**Roles**
`member`

**Access Rules**

Access rules may not be functional, or use different endpoints, so test if they work first.

```json
[{
    'id': '3725632d43d74ea2996c283a453e5ca9',
    'service': 'compute',
    'path': '/v2.1/**',
    'method': 'GET'
}, {
    'id': '74c077848cd440809f957e7cc9ef3aec',
    'service': 'compute',
    'path': '/v2.1/servers',
    'method': 'POST'
}, {
    'id': '6c4a90aa01d94723b1a868fae24b54e6',
    'service': 'compute',
    'path': '/v2.1/servers/*','
    'method': 'DELETE'
}, {
    'id': '409f134039d748e2bff85ef846e12e7e',
    'service': 'image',
    'path': '/v2/**',
    'method': 'GET'
}, {
    'id': '3e08ccf983eb44cb9eaaa950151f4069',
    'service': 'network',
    'path': '/v2.0/**',
    'method': 'GET'
}]
```

You will then download a `app-cred-xxxxxxx.sh` file. We won't be using the `clouds.yaml` file, but we will need the app-cred file.
Create a kubectl secret using the environment variables from the app-cred file.

```bash
sed 's/^export //g' app-cred-*.sh | sed 's/^#!.*$//g' > app-cred-clean.sh
# Note, you may also have to unquote some items before running the following
kubectl create secret generic openstack-scaler-credentials \
    --namespace ollama \
    --from-env-file=./app-cred-clean.sh
rm app-cred-clean.sh
```
