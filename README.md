# Pocketful · InCarousel

A self-contained wallet and payments application built by a BAND development
factory. The service implements the Pocketful track's specified synthetic wallet
model; it does not connect to banks or move real money.

Verified challenge source: `4573d5b70567b78710773267940dfe928591dc2a`.
The final fresh-clone isolated run verifies every stage folder separately:
147/147, 182/182, 188/188 and 193/193 inherited published checks. Each folder
claims its own stage. Ten independent runtime groups and sixteen custom
adversarial groups pass on matching Docker images and assets. A separate
Research source/claim handover verifies the bundle, fresh clone and local source
checks with explicit limits. Submission status is recorded separately from code.

## Repository guide

`FACTORY.md` describes the actual seats, their integration, evidence gates, measured
results and limits. `mandates/` contains generic role instructions. `room.json` is the original full console download, preserved byte for byte.
Its identity and the passing offline package check are recorded in
`evidence/submission-package.json`. Each `stage-N/` is independently buildable and retains the
earlier API behavior while adding that stage's requirements.

Follow the selected stage's `RUN.md` to build and start its Docker image. The image
must accept `PORT`, run without outbound networking and stay within 2 CPU / 2 GiB.
Test-control endpoints exist for the challenge's fixtures and populated upgrades;
they are not intended for public production deployment.

The source/evidence manifest lists immutable Git revisions, build commands,
independent execution, browser screenshots, upgrade checks and the organizer's
partial results. Unknown or unexecuted behavior remains marked as such.

## Run the application

From `stage-4/`, build `docker build -t pocketful-stage4 .`, then start
`docker run --rm -e PORT=8080 -p 127.0.0.1:8080:8080 pocketful-stage4`.
Open `http://127.0.0.1:8080/`. Challenge reset fixtures populate users;
see the stage specifications for fixture shape and the included custom probes.
The empty initial wallet service is not a bank integration or a funded account.
For the complete three-account walkthrough, use [demo/README.md](demo/README.md)
and the loopback-only fixture helper.

## Verify

The organizers' separately downloaded kickoff harness runs:
`python -m harness run --track pocketful --repo <this-repository> --all --mode isolated --out <new-directory>`.
Run `python -m harness check <this-repository> --track pocketful` before submitting.
`evidence/acceptance.json` points to actual retained test reports and their hashes.
`custom-tests/README.md` explains the independent black-box probes and disposable
fixture boundary. Failed older revisions remain in ordinary Git history.

Application code and coordinator-authored test code use MIT. Shipped fonts retain
their own OFL notices. Development agents and their provider access are not needed
to run the application.

The verified application revision above remains the source authority. Later
coordinator commits add only root documentation, the original room export and
independent test reports; all four tested stage trees retain their exact identities.
Final video/deck review and the contest submission receipt are separate from this
application release.
