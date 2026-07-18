import sys
sys.path.insert(0, '.')
from core.computer_control import ComputerController, PermissionLevel
import os

cc = ComputerController(permission_level=PermissionLevel.FULL)

print('=== 测试1: echo 命令 ===')
result = cc.shell_execute('echo hello world')
print('成功:', result.success)
print('stdout:', result.data.get('stdout', '') if result.data else 'N/A')
print('错误:', result.error)

print()
print('=== 测试2: dir 命令 ===')
result = cc.shell_execute('dir /b')
print('成功:', result.success)
stdout = result.data.get('stdout', '') if result.data else ''
print('stdout 前200字:', stdout[:200])
print('错误:', result.error)

print()
print('=== 测试3: 管道符号应该被拒绝 ===')
result = cc.shell_execute('echo hello | findstr hello')
print('成功:', result.success)
print('错误:', result.error)

print()
print('=== 测试4: 写文件到桌面 (用 copy 方式，避免重定向被拒) ===')
desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
test_file = os.path.join(desktop, 'test_shell.txt')

# 先用 echo 写一个临时文件，再 copy 过去（因为 > 重定向会被shell元字符检查拒绝）
import tempfile
tmp = os.path.join(tempfile.gettempdir(), 'test_shell_tmp.txt')
with open(tmp, 'w', encoding='utf-8') as f:
    f.write('test_content_from_shell')

result = cc.shell_execute(f'copy \"{tmp}\" \"{test_file}\"')
print('成功:', result.success)
print('错误:', result.error)
if os.path.exists(test_file):
    print('✅ 文件存在！内容:', open(test_file, 'r', encoding='utf-8').read())
    os.remove(test_file)
    print('测试文件已清理')
else:
    print('❌ 文件不存在...')

os.remove(tmp)
print()
print('测试完成！')
