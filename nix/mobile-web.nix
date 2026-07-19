# nix/mobile-web.nix — Fabric Mobile PWA (Vite/React) frontend build
{ pkgs, fabricNpmLib, ... }:
let
  npm = fabricNpmLib.mkNpmPassthru {
    folder = "apps/mobile-web";
    attr = "mobile-web";
    pname = "fabric-mobile-web";
  };

  packageJson = builtins.fromJSON (builtins.readFile (npm.src + "/apps/mobile-web/package.json"));
  version = packageJson.version;
in
pkgs.buildNpmPackage (npm // {
  pname = "fabric-mobile-web";
  inherit version;

  doCheck = false;

  buildPhase = ''
    cd apps/mobile-web
    node ../../node_modules/typescript/bin/tsc -b
    node ../../node_modules/vite/bin/vite.js build --outDir dist
    cd ../..
  '';

  installPhase = ''
    runHook preInstall
    cp -r apps/mobile-web/dist $out
    runHook postInstall
  '';
})
