# Run the judge demo locally

The competition ships four standalone containers. This demo uses the tested
Stage4 source, with three explicitly synthetic accounts. No model/BAND API or
external bank connection is needed. Use a disposable container: seeding replaces
its entire state.

From the repository root:

```sh
docker build -t pocketful-demo stage-4
docker run --rm -e PORT=8080 -p 127.0.0.1:8080:8080 pocketful-demo
```

In a second terminal, run `python demo/seed_local.py`. On systems where the command
is called `python3`, use that name. Open `http://127.0.0.1:8080/`. Sign in as
`ada@example.test`, `bob@example.test` or `cy@example.test`; all three use the
public fixture password `fixture password`. Available balances start at100,60
and40EUR. These credentials and funds are invented challenge data.

Send12.50EUR fromAda toBob, split10EUR between `ada, bob, cy`, reserve8EUR then
release it, and try an unaffordable9999EUR payment. Check the activity, request
states and available/held funds. The film records the real implementation;
the published acceptance reports cover separate isolated Docker instances.

The seed helper accepts only HTTP loopback URLs. Never aim the challenge's test
reset endpoint at a service containing anything you need to retain. The generic
lablab demo field links here to make the installable container demo explicit;
it is not advertised as a public hosted banking service.
