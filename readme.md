sudo apt update
sudo apt install -y clang llvm make libbpf-dev linux-headers-generic gcc-multilib

go mod init tcp-co
GOPROXY=direct go get github.com/cilium/ebpf/rlimit
GOPROXY=direct go mod tidy

sudo apt install -y linux-tools-generic
find /usr/lib/linux-tools -name bpftool 2>/dev/null

resultado do find btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h

 go generate
go build -o tcp-co