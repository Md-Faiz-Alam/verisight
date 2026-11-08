# Deploy the VeriSight website on AWS

The website is one container: a FastAPI server with the web page, listening on
port 8000. Uploaded files stay inside the container for at most an hour, so run
**exactly one instance**. Two instances would not share uploads.

| Option | Best for | Price model | HTTPS |
| --- | --- | --- | --- |
| **Amazon Lightsail container service** (this guide) | A portfolio or demo site | Fixed monthly price per node | Included, on a `*.cs.amazonlightsail.com` address |
| Amazon ECS Express Mode | Production traffic and autoscaling | Fargate and load balancer by the hour | Included, on a `*.ecs.<region>.on.aws` address |

AWS App Runner is no longer open to new customers; AWS recommends ECS Express
Mode instead
([availability change](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html)).

## Before you start

You need:

- an AWS account;
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), running;
- [AWS CLI version 2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html),
  signed in with `aws configure`;
- the Lightsail Control plugin, which `push-container-image` uses
  ([install guide](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-install-software.html)).

Install the plugin in PowerShell without administrator rights. This adds it to
your user PATH without truncating it:

```powershell
New-Item -ItemType Directory -Force C:\Tools\lightsailctl | Out-Null
Invoke-WebRequest https://s3.us-west-2.amazonaws.com/lightsailctl/latest/windows-amd64/lightsailctl.exe -OutFile C:\Tools\lightsailctl\lightsailctl.exe
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", "$userPath;C:\Tools\lightsailctl", "User")
```

Close and reopen PowerShell, then check every tool:

```powershell
docker version
aws --version
aws sts get-caller-identity
Get-Command lightsailctl
```

## 1. Test the container on your computer

From `F:\verisight`:

```powershell
docker build -t verisight-web .
docker run --rm -p 8000:8000 verisight-web
```

Open <http://localhost:8000>, click **Try the demo**, and check that the data
panel appears. Stop it with `Ctrl+C`.

## 2. Create the container service

The examples use Mumbai (`ap-south-1`). Use another Region if you prefer.

```powershell
$region = "ap-south-1"
aws lightsail create-container-service --region $region --service-name verisight --power micro --scale 1
aws lightsail get-container-services --region $region --service-name verisight --query "containerServices[0].state"
```

Wait until the state is `READY`, usually a few minutes. `micro` has 1 GB of
memory. In a test sweep of 118 files, uploading a 15 MB CSV peaked at about
360 MB and a heavy self-join question on it at about 530 MB, because each
question reloads the files. The deployment below therefore limits uploads to
10 MB and answers one question at a time. For larger files use `--power small`
or `medium` and raise `VERISIGHT_WEB_MAX_UPLOAD_MB`;
`aws lightsail get-container-service-powers` lists each size and price.

## 3. Push the image

```powershell
aws lightsail push-container-image --region $region --service-name verisight --label web --image verisight-web
```

The last lines of the output name the stored image, for example
`:verisight.web.1`. Use that exact name in the next step.

## 4. Deploy

Write the two deployment files without a byte-order mark, then deploy:

```powershell
$image = ":verisight.web.1"   # the name printed by step 3
$containers = @"
{
  "web": {
    "image": "$image",
    "environment": {
      "VERISIGHT_WEB_MAX_UPLOAD_MB": "10",
      "VERISIGHT_MAX_EXCEL_UNCOMPRESSED_MB": "100",
      "VERISIGHT_WEB_QUESTIONS_PER_HOUR": "20",
      "VERISIGHT_WEB_MAX_CONCURRENT_QUESTIONS": "1"
    },
    "ports": { "8000": "HTTP" }
  }
}
"@
$endpoint = @"
{
  "containerName": "web",
  "containerPort": 8000,
  "healthCheck": {
    "path": "/api/health",
    "intervalSeconds": 30,
    "timeoutSeconds": 5,
    "healthyThreshold": 2,
    "unhealthyThreshold": 3,
    "successCodes": "200"
  }
}
"@
$utf8 = New-Object System.Text.UTF8Encoding $false
[IO.File]::WriteAllText("$PWD\lightsail-containers.json", $containers, $utf8)
[IO.File]::WriteAllText("$PWD\lightsail-endpoint.json", $endpoint, $utf8)
aws lightsail create-container-service-deployment --region $region --service-name verisight --containers file://lightsail-containers.json --public-endpoint file://lightsail-endpoint.json
```

Check progress and get the public address:

```powershell
aws lightsail get-container-services --region $region --service-name verisight --query "containerServices[0].[state,url]"
```

When the state is `RUNNING`, open the `https://...cs.amazonlightsail.com/`
address. The deployment files contain no secrets, but you can delete them.

## The Gemini key

By default the site has **no server key**: each visitor pastes their own Gemini
key, which is used for that question only and never stored or logged. This
costs you nothing in Gemini quota and is the safest choice for a public site.

To let visitors ask without a key, add your key to the `environment` block in
step 4 and deploy again:

```json
"VERISIGHT_GEMINI_API_KEY": "your-key"
```

Anyone who can open your Lightsail console can read it there, and every visitor
then uses your quota, so keep `VERISIGHT_WEB_QUESTIONS_PER_HOUR` low. Never put
the key in the Dockerfile, the image or Git.

## Settings

All settings are environment variables in the `environment` block:

| Variable | Default | Meaning |
| --- | --- | --- |
| `VERISIGHT_WEB_MAX_UPLOAD_MB` | 20 | Largest accepted file |
| `VERISIGHT_WEB_MAX_FILES` | 5 | Files per upload |
| `VERISIGHT_WEB_DATASET_TTL_SECONDS` | 3600 | Uploads are deleted after this |
| `VERISIGHT_WEB_CLEANUP_INTERVAL_SECONDS` | 60 | How often expired uploads are deleted, even with no visitors |
| `VERISIGHT_WEB_MAX_DATASETS` | 100 | Stored uploads; the oldest is removed only when a new upload is valid |
| `VERISIGHT_WEB_QUESTIONS_PER_HOUR` | 30 | Questions per visitor address |
| `VERISIGHT_WEB_UPLOADS_PER_HOUR` | 60 | Uploads per visitor address |
| `VERISIGHT_WEB_DASHBOARDS_PER_HOUR` | 1200 | Dashboard updates per visitor address |
| `VERISIGHT_WEB_MAX_PREPARED_DATASETS` | 4 | Datasets kept in memory so chart filters respond at once |
| `VERISIGHT_WEB_MAX_CONCURRENT_QUESTIONS` | 2 | Questions answered at once |
| `VERISIGHT_WEB_PROVIDER_RETRIES` | 3 | Retries after a Gemini 503 |
| `VERISIGHT_MAX_EXCEL_UNCOMPRESSED_MB` | 200 | Largest unpacked size of an `.xlsx` workbook |
| `VERISIGHT_GEMINI_MODEL` | `gemini-3.1-flash-lite` | Gemini model |
| `VERISIGHT_GEMINI_CROSS_CHECK_MODEL` | same as above | Model for the independent second query |

An upload request larger than `MAX_UPLOAD_MB` × `MAX_FILES` (plus 1 MB) is
refused before any file is saved. On `micro`, also set
`VERISIGHT_MAX_EXCEL_UNCOMPRESSED_MB` to `100`.

The image sets `VERISIGHT_WEB_TRUST_FORWARDED_FOR=true`, so rate limits use the
visitor address added by AWS's load balancer.

## Update the site

After changing the code, rebuild, push and deploy the new image name:

```powershell
docker build -t verisight-web .
aws lightsail push-container-image --region $region --service-name verisight --label web --image verisight-web
# Set $image to the new name, for example ":verisight.web.2", then rerun step 4.
```

## Stop paying

```powershell
aws lightsail delete-container-service --region $region --service-name verisight
```

A container service is billed every hour it exists, even while stopped or idle.
Check the current price on the
[Lightsail pricing page](https://aws.amazon.com/lightsail/pricing/) before
creating it.

## Later: ECS Express Mode

For autoscaling and production traffic, push the same image to Amazon ECR and
follow AWS's
[Express Mode getting started guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-getting-started.html)
with `"containerPort": 8000` and `--health-check-path "/api/health"`. Keep one
task (`"minTaskCount": 1, "maxTaskCount": 1`) until uploads move to shared
storage such as Amazon S3.
