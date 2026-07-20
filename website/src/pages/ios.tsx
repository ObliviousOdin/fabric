import React from "react";
import Layout from "@theme/Layout";

// Once the first build is live, paste the public TestFlight invitation link
// here (App Store Connect -> TestFlight -> your tester group -> Public Link).
// Until this is a real https:// link the page shows a "coming soon" state, so
// it is safe to ship before the beta exists.
const TESTFLIGHT_URL = "";

export default function IosDownloadPage(): React.ReactElement {
  const live = TESTFLIGHT_URL.startsWith("https://");

  return (
    <Layout
      title="Fabric for iPhone"
      description="Install the Fabric iOS app through TestFlight and connect it to your own Fabric gateway."
    >
      <main className="container margin-vert--xl">
        <div className="row">
          <div className="col col--8 col--offset-2">
            <h1>Fabric for iPhone</h1>
            <p className="hero__subtitle">
              A native remote control for your own Fabric agent. The app is a
              thin client: it connects to a <code>fabric serve</code> gateway you
              run, so your files, tools, and sessions never leave that machine.
            </p>

            {live ? (
              <p>
                <a
                  className="button button--primary button--lg"
                  href={TESTFLIGHT_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  Join the TestFlight beta
                </a>
              </p>
            ) : (
              <div
                className="admonition admonition-info alert alert--info"
                role="alert"
                style={{ padding: "1rem 1.25rem", borderRadius: 8 }}
              >
                <strong>Beta invite link coming soon.</strong> The first build is
                being prepared in TestFlight. Maintainers: paste the public
                TestFlight link into <code>website/src/pages/ios.tsx</code> to
                turn this into a live install button.
              </div>
            )}

            <h2>Requirements</h2>
            <ul>
              <li>An iPhone running iOS 17 or newer</li>
              <li>
                Apple's free <strong>TestFlight</strong> app from the App Store
              </li>
              <li>A reachable Fabric gateway — see the steps below</li>
            </ul>

            <h2>Install &amp; connect</h2>
            <ol>
              <li>
                Install <strong>TestFlight</strong> from the App Store.
              </li>
              <li>
                Tap <strong>Join the TestFlight beta</strong> above and accept
                the invitation.
              </li>
              <li>
                On the machine running Fabric, start a gateway:{" "}
                <code>fabric mobile --install none</code>. It prints a pairing QR
                code.
              </li>
              <li>
                Open Fabric on your phone and scan the QR to pair. Not on the
                same network? Put <a href="https://tailscale.com">Tailscale</a>{" "}
                on both the phone and the gateway host and pair over the tailnet.
              </li>
            </ol>

            <p>
              A public gateway must use HTTPS; LAN and tailnet addresses work out
              of the box. Building from source or want the full contract? See the{" "}
              <a href="https://github.com/ObliviousOdin/fabric/blob/main/apps/mobile/README.md">
                mobile README
              </a>
              .
            </p>
          </div>
        </div>
      </main>
    </Layout>
  );
}
