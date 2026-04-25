!/bin/bash
echo "--- install reductstore"
echo "    machine raspberry pi4"
echo "    Compilation finished `release` profile [optimized] target(s) in 16m 31s"

sudo apt install libprotobuf-dev protobuf-compiler
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

source $HOME/.cargo/env
cargo --version
rustc --version
cargo install reductstore

mkdir -p $HOME/medias
