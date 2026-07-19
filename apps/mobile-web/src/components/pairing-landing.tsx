import { IconBrandApple, IconBrandAndroid, IconDownload, IconExternalLink } from "@tabler/icons-react";
import { useEffect, useState } from "react";

interface PairingLandingProps {
  onContinue: () => void;
  pairingUri: string;
}

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export function PairingLanding({ onContinue, pairingUri }: PairingLandingProps) {
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
        <p className="eyebrow">Your Fabric is ready</p>
        <h1 id="pairing-heading">Pick up the same work on your phone.</h1>
        <p>
          This page belongs to the Fabric gateway you just scanned. Open the native
          app when it is installed, or use the private same-origin web app now.
        </p>
      </section>

      <section className="pairing-actions" aria-label="Open Fabric Mobile">
        <a className="primary-button pairing-action" href={pairingUri}>
          <IconExternalLink size={19} /> Open the Fabric app
        </a>
        <button className="secondary-button pairing-action" type="button" onClick={onContinue}>
          Continue in browser
        </button>
        {installPrompt ? (
          <button className="secondary-button pairing-action" type="button" onClick={() => void install()}>
            <IconDownload size={19} /> Install web app
          </button>
        ) : (
          <p className="install-note">
            <IconBrandApple size={17} /> iPhone: Share → Add to Home Screen
            <br />
            <IconBrandAndroid size={17} /> Android: browser menu → Install app
          </p>
        )}
        <p className="pairing-security">
          Pairing details were read from the private URL fragment and removed from
          browser history. Passwords and one-time codes are never stored.
        </p>
      </section>
    </main>
  );
}
