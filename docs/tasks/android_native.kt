// 由 DSH Art UI/UX Pro Max 生成的设计 token（Compose 侧）
// 说明：这是骨架示例，未接入具体工程的导航与状态管理。

private val ArtColors = lightColorScheme(
    primary = Color(0xFF8a4b2a),
    background = Color(0xFFfaf8f4),
    onBackground = Color(0xFF15130f),
    surface = Color(0xFFffffff),
)

@Composable
fun ArtHomeScreen(modifier: Modifier = Modifier) {
    Scaffold(topBar = { TopAppBar(title = { Text("首页") }) }) { padding ->
        LazyColumn(
            modifier = modifier.padding(padding).fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { Text("今日概览", style = MaterialTheme.typography.headlineSmall) }
            items(3) { index ->
                Card(shape = RoundedCornerShape(12.dp)) {
                    Column(Modifier.padding(16.dp)) {
                        Text("指标 " + (index + 1), style = MaterialTheme.typography.titleMedium)
                        Text("数值占位", style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }
}
