---
name: vercel-react-native
description: Vercel RN 最佳实践 / Vercel RN
provider_hint: text
read_only: true
kind: instruction
triggers:
- React Native
- RN 开发
- Expo 项目
- 移动端 App 开发
- RN 性能优化
- 原生应用开发
- 用 Expo 做
- Expo 路由
---

# Vercel RN 最佳实践（vercel-react-native）

写或审 React Native / Expo 应用时套用。重点在**导航结构、列表性能、平台差异、资源加载**——移动端的约束（内存、网络、手势）和 Web 完全不同，照搬 Web 习惯一定会出问题。

## 铁律

1. **导航用文件式路由**：Expo Router 里文件与目录即路由，不要手写层层嵌套的导航配置；深链与返回行为交给路由系统保证。
2. **长列表必须虚拟化**：使用 `FlashList` 或 `FlatList`，绝不用 `ScrollView` 渲染上百条数据；列表项组件要 `memo` 化。
3. **图片按需与缓存**：用 `expo-image` 做缓存、占位与尺寸裁剪，避免大图直接塞进 `<Image>`。
4. **平台差异显式处理**：用 `Platform.select` 或平台后缀文件处理 iOS 与 Android 差异，别假设两端表现一致。
5. **不依赖 Web API**：`localStorage`、`window` 在 RN 里不存在，持久化用 `expo-secure-store` 或 `AsyncStorage`。

## 步骤

1. **定导航结构**：规划 Tab / Stack / Modal 层级，用 Expo Router 的目录表达，确认深链与返回栈正确。
2. **查列表**：找出所有长列表并换成虚拟化组件，检查 `keyExtractor`、`getItemType` 等性能参数。
3. **查图片与资源**：改用 `expo-image`，设置 `contentFit`、`placeholder` 与缓存策略。
4. **查手势与动画**：动画用 `react-native-reanimated` 跑在 UI 线程，避免 JS 线程卡顿。
5. **查安全区与键盘**：处理 `SafeAreaView` / `KeyboardAvoidingView`，确保刘海屏与输入框不被遮挡。
6. **查平台与权限**：权限申请走 `expo-*` 模块，检查 iOS/Android 声明与降级路径。
7. **给结论**：注明文件、问题、影响与修法，附关键 diff。

## 输出形态

```
## 结构问题
| 文件 | 问题 | 修法 |

## 列表性能
- 列表 X：ScrollView → FlashList，补 keyExtractor / memo

## 平台差异
- iOS：…  Android：…（Platform.select 或 .ios.tsx / .android.tsx）

## 修改后片段
（关键 diff）
```

## 反面例子（不要这样）

- 用 `ScrollView` 渲染几百条记录，滚动卡顿甚至崩溃。
- 在 RN 里调 `window.localStorage`，真机直接报错。
- 大图不裁剪、不缓存，列表滚动时反复闪烁加载。
- 动画在 JS 线程做，频繁掉帧。
- 忽略安全区，内容被刘海或底部横条遮挡。
