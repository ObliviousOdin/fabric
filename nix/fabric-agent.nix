# nix/fabric-agent.nix — Overridable Fabric package
#
# callPackage auto-wires nixpkgs args; flake inputs are passed explicitly.
# Users override via:
#   pkgs.fabric-agent.override { extraPythonPackages = [...]; }
#   pkgs.fabric-agent.override { extraDependencyGroups = [ "hindsight" ]; }
{
  lib,
  stdenv,
  makeWrapper,
  callPackage,
  python312,
  nodejs_22,
  electron,
  ripgrep,
  git,
  openssh,
  ffmpeg,
  tirith,

  # linux-only deps
  wl-clipboard,
  xclip,

  # Flake inputs — passed explicitly by packages.nix and overlays.nix
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
  npm-lockfile-fix,
  # Locked git revision of the flake source — embedded so banner.py can
  # check for updates without needing a local .git directory. Null for
  # impure / dirty builds where flakes can't determine a rev.
  rev ? null,
  # Overridable parameters
  extraPythonPackages ? [ ],
  extraDependencyGroups ? [ ],
}:
let
  nodejs = nodejs_22;
  mkFabricVenv =
    extraDependencyGroups:
    callPackage ./python.nix {
      inherit uv2nix pyproject-nix pyproject-build-systems;
      dependency-groups = [ "all" ] ++ extraDependencyGroups;
    };

  fabricVenv = (mkFabricVenv extraDependencyGroups).venv;

  fabricNpmLib = callPackage ./lib.nix {
    inherit npm-lockfile-fix nodejs;
  };

  fabricTui = callPackage ./tui.nix {
    inherit fabricNpmLib;
  };

  fabricWeb = callPackage ./web.nix {
    inherit fabricNpmLib;
  };

  fabricMobileWeb = callPackage ./mobile-web.nix {
    inherit fabricNpmLib;
  };

  # i18n locale catalogs (locales/*.yaml). Keep a visible copy in the store for
  # packaged-asset inspection. Runtime resolution has one contract: setuptools
  # data-files materialized into the venv's data scheme, which agent/i18n.py
  # discovers without an environment override.
  #
  # Plain cleanSource (no __pycache__ filter): locales/ is bare *.yaml, never
  # compiled, so it never carries a __pycache__ dir to exclude.
  bundledLocales = lib.cleanSource ../locales;

  runtimeDeps = [
    nodejs
    ripgrep
    git
    openssh
    ffmpeg
    tirith
  ]
  ++ lib.optionals stdenv.isLinux [
    wl-clipboard
    xclip
  ];

  runtimePath = lib.makeBinPath runtimeDeps;

  sitePackagesPath = python312.sitePackages;

  # Walk propagatedBuildInputs to include transitive Python deps in PYTHONPATH.
  # Without this, a plugin listing e.g. requests as a dep would fail at runtime
  # if requests isn't already in the sealed uv2nix venv.
  allExtraPythonPackages = python312.pkgs.requiredPythonModules extraPythonPackages;

  pythonPath = lib.makeSearchPath sitePackagesPath allExtraPythonPackages;

  checkPackageCollisions = ''
    import pathlib, sys, re

    def canonical(name):
        return re.sub(r'[-_.]+', '-', name).lower()

    # Collect core venv package names
    core = set()
    venv_sp = pathlib.Path('${fabricVenv}/${sitePackagesPath}')
    for di in venv_sp.glob('*.dist-info'):
        meta = di / 'METADATA'
        if meta.exists():
            for line in meta.read_text().splitlines():
                if line.startswith('Name:'):
                    core.add(canonical(line.split(':', 1)[1].strip()))
                    break

    # Check each extra package for collisions
    extras_dirs = [${lib.concatMapStringsSep ", " (p: "'${toString p}'") allExtraPythonPackages}]
    for edir in extras_dirs:
        sp = pathlib.Path(edir) / '${sitePackagesPath}'
        if not sp.exists():
            continue
        for di in sp.glob('*.dist-info'):
            meta = di / 'METADATA'
            if not meta.exists():
                continue
            for line in meta.read_text().splitlines():
                if line.startswith('Name:'):
                    pkg = canonical(line.split(':', 1)[1].strip())
                    if pkg in core:
                        print(f'ERROR: plugin package \"{pkg}\" collides with a package in fabric sealed venv', file=sys.stderr)
                        print(f'  from: {di}', file=sys.stderr)
                        print(f'  Remove this dependency from extraPythonPackages.', file=sys.stderr)
                        sys.exit(1)
                    break

    print('No collisions found.')
  '';
in
stdenv.mkDerivation (finalAttrs: {
  pname = "fabric-agent";
  version = (fromTOML (builtins.readFile ../pyproject.toml)).project.version;

  dontUnpack = true;
  dontBuild = true;
  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/fabric-agent $out/bin
    cp -r ${bundledLocales} $out/share/fabric-agent/locales
    cp -r ${fabricWeb} $out/share/fabric-agent/web_dist
    cp -r ${fabricMobileWeb} $out/share/fabric-agent/mobile_web_dist

    mkdir -p $out/ui-tui
    cp -r ${fabricTui}/lib/fabric-tui/* $out/ui-tui/

    makeWrapper ${fabricVenv}/bin/fabric $out/bin/fabric \
      --suffix PATH : "${runtimePath}" \
      --set FABRIC_WEB_DIST $out/share/fabric-agent/web_dist \
      --set FABRIC_TUI_DIR $out/ui-tui \
      --add-flags ${lib.escapeShellArg (if rev == null then "" else "--package-revision ${rev}")} \
      ${lib.optionalString (extraPythonPackages != [ ]) ''--suffix PYTHONPATH : "${pythonPath}"''}

    ${lib.optionalString (extraPythonPackages != [ ]) ''
      echo "=== Checking for plugin/core package collisions ==="
      ${fabricVenv}/bin/python3 -c "${checkPackageCollisions}"
      echo "=== No collisions ==="
    ''}

    runHook postInstall
  '';

  passthru =
    let
      devPython = (mkFabricVenv (extraDependencyGroups ++ [ "dev" ])).editableVenv;
    in
    {
      inherit
        fabricTui
        fabricWeb
        fabricMobileWeb
        fabricNpmLib
        fabricVenv
        ;

      # `fabricDesktop` references `finalAttrs.finalPackage` (this whole
      # derivation, after all overrides are applied) so the desktop wrapper
      # can prepend its `/bin` to PATH.  The desktop's resolver step 4
      # ("existing fabric on PATH") then picks up the fully wrapped
      # `fabric` binary — venv with all deps, bundled skills/plugins,
      # runtime PATH (ripgrep/git/ffmpeg/etc).  No re-implementation
      # of the agent resolution in the desktop wrapper.
      fabricDesktop = callPackage ./desktop.nix {
        inherit fabricNpmLib electron;
        fabricAgent = finalAttrs.finalPackage;
      };

      devDeps = runtimeDeps ++ [ devPython ];
    };

  meta = with lib; {
    description = "AI agent with advanced tool-calling capabilities";
    homepage = "https://github.com/ObliviousOdin/fabric";
    mainProgram = "fabric";
    license = licenses.mit;
    platforms = platforms.unix;
  };
})
