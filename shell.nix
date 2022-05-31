with import <nixpkgs> {};

stdenv.mkDerivation {
  name = "cometa-contracts";
  buildInputs = [
    # System requirements.
    readline

    # Python requirements (enough to get a virtualenv going).
    python38Full
    python38Packages.pyflakes
    pipenv

    # Node (for running backend-based Reach scripts)
    nodejs-16_x
  ];
  src = null;
  shellHook = ''
    # Allow the use of wheels.
    SOURCE_DATE_EPOCH=$(date +%s)

    # Augment the dynamic linker path
    export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:${R}/lib/R/lib:${readline}/lib

    # Enter pipenv
    pipenv shell

    # Set cometa env
    export COMETA_ENVIRONMENT=test
  '';
}
