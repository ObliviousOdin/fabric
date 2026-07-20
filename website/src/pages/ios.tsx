import React from "react";
import Layout from "@theme/Layout";

// Once the public beta group is live, paste the TestFlight invitation link
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
              thin client that connects to a <code>fabric serve</code> gateway
              you control; execution and provider choices remain part of that
              Fabric setup instead of moving into a second mobile backend.
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
                <strong>Public beta invite coming soon.</strong> An internal
                TestFlight preview is already running. Invited testers can open
                it from TestFlight; everyone else can join when the public group
                opens. Maintainers: paste that public invitation into{" "}
                <code>website/src/pages/ios.tsx</code> to enable the button.
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
              {live ? (
                <li>
                  Tap <strong>Join the TestFlight beta</strong> above and accept
                  the invitation.
                </li>
              ) : (
                <li>
                  If you are already an internal tester, open the Fabric invite
                  in TestFlight. Otherwise, return when the public invitation is
                  published.
                </li>
              )}
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
              Use HTTPS for any gateway reached by hostname or IP, including a
              tailnet address. Plain HTTP is limited by iOS transport security
              and should not be used for a remote TestFlight connection. Building
              from source or want the full contract? See the{" "}
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
