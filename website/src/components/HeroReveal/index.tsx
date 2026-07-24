import { useEffect, useRef, useState } from "react";

import useBaseUrl from "@docusaurus/useBaseUrl";

import styles from "./styles.module.css";

/**
 * Cinematic hero reveal for the marketing landing page: the Fabric mark
 * assembling into its guardian form.
 *
 * This is a deliberately bold brand moment for the marketing site only — it is
 * NOT part of the in-app Woven Operations language (web/DESIGN.md), which keeps
 * motion to opacity/transform and avoids decorative chrome. To stay light and
 * honest it: renders a static frame on the server, only mounts the <video>
 * (and fetches its bytes) once the hero scrolls into view, plays once and rests
 * on the final frame, and never plays under prefers-reduced-motion — reduced
 * viewers get the final guardian pose as a still image instead.
 */
export default function HeroReveal(): React.JSX.Element {
  const posterUrl = useBaseUrl("/img/reveal/fabric-reveal-poster.png");
  const endUrl = useBaseUrl("/img/reveal/fabric-reveal-end.png");
  const videoUrl = useBaseUrl("/img/reveal/fabric-reveal.mp4");

  const [ready, setReady] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [played, setPlayed] = useState(false);
  const figureRef = useRef<HTMLElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Client-only: decide once mounted so server render and first client render
  // agree (both show the poster still), then react to the motion preference.
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = (): void => setReduced(query.matches);
    update();
    setReady(true);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  // Lazy play-once: the observer is also the load gate — with preload="none"
  // the ~419 KB clip is fetched only when the hero nears the viewport.
  useEffect(() => {
    if (!ready || reduced) return;
    const figure = figureRef.current;
    const video = videoRef.current;
    if (!figure || !video) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            void video.play().catch(() => {});
            setPlayed(true);
            observer.disconnect();
            break;
          }
        }
      },
      { threshold: 0.35 },
    );
    observer.observe(figure);
    return () => observer.disconnect();
  }, [ready, reduced]);

  const replay = (): void => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = 0;
    void video.play().catch(() => {});
  };

  const showVideo = ready && !reduced;
  const staticSrc = ready && reduced ? endUrl : posterUrl;
  const staticAlt =
    ready && reduced
      ? "The Fabric F mark resolved into its guardian form, arms spread in a wide stance."
      : "The Fabric F mark, ready to unfold.";

  return (
    <figure
      ref={figureRef}
      className={styles.reveal}
      aria-labelledby="fabric-reveal-title"
    >
      <figcaption className={styles.header}>
        <span id="fabric-reveal-title">FABRIC / GUARDIAN</span>
        <span className={styles.tag}>Reveal</span>
      </figcaption>
      <div className={styles.stage}>
        {showVideo ? (
          <video
            ref={videoRef}
            className={styles.media}
            muted
            playsInline
            preload="none"
            poster={posterUrl}
            width={512}
            height={512}
          >
            <source src={videoUrl} type="video/mp4" />
          </video>
        ) : (
          <img
            className={styles.media}
            src={staticSrc}
            width={512}
            height={512}
            alt={staticAlt}
            loading="lazy"
          />
        )}
        {showVideo && played ? (
          <button type="button" className={styles.replay} onClick={replay}>
            <span aria-hidden="true">↻</span> Replay
          </button>
        ) : null}
      </div>
    </figure>
  );
}
