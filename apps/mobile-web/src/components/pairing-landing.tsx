import { IconBrandApple, IconBrandAndroid, IconDownload, IconExternalLink } from "@tabler/icons-react";
import { useEffect, useState } from "react";

interface PairingLandingProps {
  enrollmentRequired?: boolean;
  onContinue: () => void;
  pairingUri: string;
}

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export function PairingLanding({
  enrollmentRequired = false,
  onContinue,
  pairingUri,
}: PairingLandingProps) {
  const [installPrompt, setInstallPrompt] = useState<InstallPromptEvent | null>(null);

  useEffect(() => {
    const capture = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as InstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", capture);
    return () => window.removeEventListener("beforeinstallprompt", capture);
  }, []);

  const install = async () => {
    if (!installPrompt) {
      return;
    }
    await installPrompt.prompt();
    await installPrompt.userChoice;
    setInstallPrompt(null);
  };

  return (
    <main className="pairing-page">
      <section className="pairing-copy" aria-labelledby="pairing-heading">
        <div className="brand-lockup">
          <img src={`${import.meta.env.BASE_URL}fabric-mark-192.png`} alt="" />
          <span>Fabric</span>
        </div>
        <p className="eyebrow">
          {enrollmentRequired ? "Secure setup required" : "Your Fabric is ready"}
        </p>
        <h1 id="pairing-heading">
          {enrollmentRequired
            ? "Pair this phone securely."
            : "Pick up the same work on your phone."}
        </h1>
        <p>
          {enrollmentRequired
            ? "This time-limited code needs device enrollment. A browser session cannot claim a device credential."
            : "This page belongs to the Fabric gateway you just scanned. Open the native app when it is installed, or use the private same-origin web app now."}
        </p>
      </section>

      <section className="pairing-actions" aria-label="Open Fabric Mobile">
        <a className="primary-button pairing-action" href={pairingUri}>
          <IconExternalLink size={19} /> Open the Fabric app
        </a>
        <button className="secondary-button pairing-action" type="button" onClick={onContinue}>
          {enrollmentRequired ? "See setup requirements" : "Continue in browser"}
        </button>
        {!enrollmentRequired &&
          (installPrompt ? (
            <button className="secondary-button pairing-action" type="button" onClick={() => void install()}>
              <IconDownload size={19} /> Install web app
            </button>
          ) : (
            <p className="install-note">
              <IconBrandApple size={17} /> iPhone: Share → Add to Home Screen
              <br />
              <IconBrandAndroid size={17} /> Android: browser menu → Install app
            </p>
          ))}
        <p className="pairing-security">
          {enrollmentRequired
            ? "The one-time handoff was read from the private URL fragment and removed from browser history. It is not saved or sent by this browser page."
            : "Pairing details were read from the private URL fragment and removed from browser history. Passwords and one-time codes are never stored."}
        </p>
      </section>
    </main>
  );
}

interface EnrollmentBrowserNoticeProps {
  pairingUri: string;
}

export function EnrollmentBrowserNotice({
  pairingUri,
}: EnrollmentBrowserNoticeProps) {
  return (
    <main className="pairing-page">
      <section className="pairing-copy" aria-labelledby="enrollment-heading">
        <div className="brand-lockup">
          <img src={`${import.meta.env.BASE_URL}fabric-mark-192.png`} alt="" />
          <span>Fabric</span>
        </div>
        <p className="eyebrow">Device enrollment</p>
        <h1 id="enrollment-heading">Finish setup in a supported Fabric app.</h1>
        <p>
          This browser can use an authenticated browser session, but it cannot
          safely store or present a device-bound credential.
        </p>
      </section>
      <section className="pairing-actions" aria-label="Enrollment requirements">
        <a className="primary-button pairing-action" href={pairingUri}>
          <IconExternalLink size={19} /> Open the Fabric app
        </a>
        <p className="pairing-security">
          This Fabric Mobile build recognizes the secure handoff but cannot
          complete enrollment yet. Ask the gateway owner for a supported
          connection method or update the app and gateway together.
        </p>
      </section>
    </main>
  );
}
