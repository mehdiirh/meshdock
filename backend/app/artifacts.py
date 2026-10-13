"""Pinned upstream artifacts. Changes require release notes and checksum review."""

ARTIFACTS = {
    "backhaul": {
        "x86_64": (
            "https://github.com/Musixal/Backhaul/releases/download/v0.7.2/backhaul_linux_amd64.tar.gz",
            "57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc",
        ),
        "aarch64": (
            "https://github.com/Musixal/Backhaul/releases/download/v0.7.2/backhaul_linux_arm64.tar.gz",
            "9a424c97ff16fc3f682e8314c418790d2b5bf3136e008edbb6cd402ea00999f6",
        ),
    },
    "rathole": {
        "x86_64": (
            "https://github.com/rathole-org/rathole/releases/download/v0.5.0/rathole-x86_64-unknown-linux-gnu.zip",
            "3e7d0d0f365120cd3cd351d147d1a12ee960c8068b464d4dd533a3821873b80e",
        ),
        "aarch64": (
            "https://github.com/rathole-org/rathole/releases/download/v0.5.0/rathole-aarch64-unknown-linux-musl.zip",
            "fa4a6fc63d86f8f1faa7c103a845e4715ce79a048455c0eec897b27237576564",
        ),
    },
}

FRP_ARTIFACTS = {
    "x86_64": (
        "https://github.com/fatedier/frp/releases/download/v0.71.0/frp_0.71.0_linux_amd64.tar.gz",
        "84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716",
    ),
    "aarch64": (
        "https://github.com/fatedier/frp/releases/download/v0.71.0/frp_0.71.0_linux_arm64.tar.gz",
        "f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266",
    ),
}
ARTIFACTS.update(
    {
        "frpc": FRP_ARTIFACTS,
        "frps": FRP_ARTIFACTS,
        "hysteria": {
            "x86_64": (
                "https://github.com/HyNetworks/hysteria/releases/download/app/v2.13.0/hysteria-linux-amd64",
                "907ba8c9693edb104b20582681fb7dc15639d5b64a9cbb616a7b539190a86691",
            ),
            "aarch64": (
                "https://github.com/HyNetworks/hysteria/releases/download/app/v2.13.0/hysteria-linux-arm64",
                "a68a61a84452ca250ce0368202521965ca9cc9d801a404f1dc9008ac6cf677a7",
            ),
        },
    }
)
