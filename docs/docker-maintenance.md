# Docker maintenance releases

This fork retains the original author and GPLv3 license. Version 2.0.1 is based
on ee3700c (SEND_GIFT_V2 support), not on the separate local Windows maintenance
work. No recording data, cookies or personal settings are part of the image.

## Run 2.0.3

```sh
docker pull ghcr.io/junpakugenso/blrec:2.0.3
docker run -d --name blrec --restart unless-stopped \
  -p 127.0.0.1:2233:2233 \
  -v blrec-cfg:/cfg -v blrec-log:/log -v blrec-rec:/rec \
  ghcr.io/junpakugenso/blrec:2.0.3
```

Open http://localhost:2233. Both linux/amd64 and linux/arm64 are supported;
Docker selects the host platform. Use bind mounts instead of named volumes if
you need recordings directly in a host folder. Do not expose the API to the
Internet without authentication and access controls.

## Upgrade or roll back

Before upgrading, stop recording and back up /cfg. Note the current image tag
or digest and the volume/bind-mount arguments. Pull the desired fixed version,
stop and remove only the old container (never its volumes), and recreate it with
the same mounts. To roll back, repeat using the recorded previous tag/digest.
There is no database or settings migration in 2.0.3. Mount the entire /cfg directory:
atomic replacement cannot work on some single-file bind mounts. Avoid `latest` for deployments
where reproducibility matters; never use `docker volume rm` or `compose down -v`
as part of an upgrade.

For the named-volume example above, after finishing recording:

```sh
docker pull ghcr.io/junpakugenso/blrec:2.0.3
docker stop blrec
docker cp blrec:/cfg ./blrec-cfg-backup-before-2.0.3
docker rm blrec
docker run -d --name blrec --restart unless-stopped \
  -p 127.0.0.1:2233:2233 \
  -v blrec-cfg:/cfg -v blrec-log:/log -v blrec-rec:/rec \
  ghcr.io/junpakugenso/blrec:2.0.3
```

Use a new backup directory if that name already exists. Preserve your own port,
mounts, environment and extra arguments if they differ from this example.
To roll back this example without deleting data:

```sh
docker pull ghcr.io/junpakugenso/blrec:2.0.2
docker stop blrec
docker rm blrec
docker run -d --name blrec --restart unless-stopped \
  -p 127.0.0.1:2233:2233 \
  -v blrec-cfg:/cfg -v blrec-log:/log -v blrec-rec:/rec \
  ghcr.io/junpakugenso/blrec:2.0.2
```

## Release procedure

1. Increment `src/blrec/__init__.py` to the next patch (next: 2.0.4), only when
   preparing a new release. Update this document's release notes/examples.
2. Commit and push to master. Wait for both Docker build/test jobs to pass.
3. Tag the same tested commit `v<version>` and push that tag. Tag and package
   versions must match; branch pushes do not publish images. If GitHub does not
   start a run automatically, dispatch this workflow explicitly on that same tag.
   Manual runs on master only validate and cannot publish.
4. The tag workflow builds/tests both architectures, exports those exact images,
   publishes candidate tags, verifies anonymous pulls and startup, then promotes
   to `<version>` and `latest`. Existing version tags are never overwritten.
5. For the FIRST publication, GitHub may create the package as private. In
   https://github.com/users/junpakugenso/packages/container/blrec/settings change
   package visibility to Public. If the public-pull gate failed, rerun the same
   workflow after changing visibility; do not increment the version for a retry.
6. Save the workflow URL and final manifest digest with the release notes.
   If a version was published but a later step failed, inspect the existing image
   and repair only the incomplete promotion/verification; do not overwrite it.

Public CI uses synthetic gift fixtures; the optional recording replay uses
BLREC_GIFT_SAMPLE_ZIP locally only. Build/tests use native amd64 and ARM64 runners;
the release job additionally verifies public ARM pulls/startup under QEMU. CI proves
container startup, API/UI availability, settings persistence, FFmpeg and gift
conversion; it does not prove recording a newly arriving live gift.

## 2.0.3 changes and acceptance scope

- Create the shared network pool lazily in the running event loop; isolate pools
  across loops while retaining the 200-connection limit, timeout and proxy policy.
- Close the pool after all application tasks are successfully destroyed; create a
  fresh pool on restart. Failed task shutdown retains the pool for safe retry.
- Cover local HTTP requests, connection reuse, cancellation and application
  shutdown/restart with regression tests, without changing gift/XML or settings.
- Standalone users of internal helpers/Live must explicitly close their pool.
  See [lifecycle contract and limits](stability-stage2.md). Avoid concurrent
  management requests during an in-app restart; lossless concurrent restart,
  real live recording and long-duration soak tests are not claimed.

## 2.0.2 changes and acceptance scope

- Preserve the previous configuration when serialization, flushing or replacement fails;
  serialize snapshot writes, including when callers are cancelled.
- Restore lifecycle state after failed transitions; unwind successfully started
  recorder helpers and listeners after failed startup.
- Deliver HLS completion, unblock full-queue shutdown and avoid the natural
  completion callback waiting on its own cleanup thread.
- Retain dependency versions, configuration fields and gift/XML behavior.
- The release gates run the regression suite and real container startup on both
  architectures. The user waived the private recording sample replay for this
  release; no live Bilibili recording or long-duration soak test is claimed.

## 2.0.1 changes

- Decode SEND_GIFT_V2 into the existing XML gift pipeline; retain SEND_GIFT.
- Build Python 3.11/Bookworm images from a pinned multi-platform base digest,
  with Docker-only aiohttp/setuptools/protobuf constraints and packaged web assets.
- Preserve successful CLI exit status for `--version` / `--help`.
- Only GHCR version releases are enabled; Windows, PyPI and Docker Hub jobs are
  retained for historical reference but cannot publish from this fork.
