#!/bin/bash
set -e

# 检查是否安装了 swiftformat
if ! command -v swiftformat &> /dev/null; then
    echo "Error: swiftformat is not installed."
    echo "Please install it using: brew install swiftformat"
    exit 1
fi

echo "🎨 Formatting Swift code in nmp_socks directory..."

# 运行 swiftformat
# --indent 4: 使用4个空格缩进
# --allman false: 不使用 Allman 风格的大括号
# --trimwhitespace always: 总是移除行尾空格
# --swiftversion 5.0: 指定 Swift 版本
swiftformat . \
    --indent 4 \
    --allman false \
    --trimwhitespace always \
    --swiftversion 5.0 \
    --exclude nmp.xcodeproj,nmp_socks.xcodeproj

echo "✅ Swift code formatting complete!"
