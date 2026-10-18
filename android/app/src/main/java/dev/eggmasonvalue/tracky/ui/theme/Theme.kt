@file:OptIn(androidx.compose.material3.ExperimentalMaterial3ExpressiveApi::class)

package dev.eggmasonvalue.tracky.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialExpressiveTheme
import androidx.compose.material3.MotionScheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.eggmasonvalue.tracky.R

private val TrackyLightColors = lightColorScheme(
    primary = Color(0xFF405D44),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFC2E9C5),
    onPrimaryContainer = Color(0xFF0B3515),
    secondary = Color(0xFF506352),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFD3E8D2),
    onSecondaryContainer = Color(0xFF172B1B),
    tertiary = Color(0xFF39656B),
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFBCEBF1),
    onTertiaryContainer = Color(0xFF002F34),
    error = Color(0xFFBA1A1A),
    onError = Color.White,
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    background = Color(0xFFF7FBF3),
    onBackground = Color(0xFF191C19),
    surface = Color(0xFFF7FBF3),
    onSurface = Color(0xFF191C19),
    surfaceVariant = Color(0xFFDEE5DB),
    onSurfaceVariant = Color(0xFF424940),
    outline = Color(0xFF727970),
    outlineVariant = Color(0xFFC2C9BF),
    inverseSurface = Color(0xFF2E312E),
    inverseOnSurface = Color(0xFFEFF2EC),
    inversePrimary = Color(0xFFA7CDAA),
)

private val TrackyDarkColors = darkColorScheme(
    primary = Color(0xFFA7CDAA),
    onPrimary = Color(0xFF12391C),
    primaryContainer = Color(0xFF294F2E),
    onPrimaryContainer = Color(0xFFC2E9C5),
    secondary = Color(0xFFB8CCB7),
    onSecondary = Color(0xFF233426),
    secondaryContainer = Color(0xFF394B3B),
    onSecondaryContainer = Color(0xFFD3E8D2),
    tertiary = Color(0xFFA1CED4),
    onTertiary = Color(0xFF00363B),
    tertiaryContainer = Color(0xFF1F4D52),
    onTertiaryContainer = Color(0xFFBCEBF1),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    background = Color(0xFF111411),
    onBackground = Color(0xFFE1E3DE),
    surface = Color(0xFF111411),
    onSurface = Color(0xFFE1E3DE),
    surfaceVariant = Color(0xFF424940),
    onSurfaceVariant = Color(0xFFC2C9BF),
    outline = Color(0xFF8C9389),
    outlineVariant = Color(0xFF424940),
    inverseSurface = Color(0xFFE1E3DE),
    inverseOnSurface = Color(0xFF2E312E),
    inversePrimary = Color(0xFF405D44),
)

private val GoogleSansFlex = FontFamily(
    Font(R.font.google_sans_flex, FontWeight.Normal),
)
private val TrackyShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(14.dp),
    medium = RoundedCornerShape(20.dp),
    large = RoundedCornerShape(30.dp),
    extraLarge = RoundedCornerShape(40.dp),
)
private val BaseTypography = Typography()
private val TrackyTypography = Typography(
    displayLarge = BaseTypography.displayLarge.merge(
        TextStyle(fontFamily = GoogleSansFlex, fontWeight = FontWeight.SemiBold, fontSize = 64.sp),
    ),
    headlineLarge = BaseTypography.headlineLarge.merge(
        TextStyle(fontFamily = GoogleSansFlex, fontWeight = FontWeight.SemiBold),
    ),
    headlineMedium = BaseTypography.headlineMedium.merge(
        TextStyle(fontFamily = GoogleSansFlex, fontWeight = FontWeight.SemiBold),
    ),
    titleLarge = BaseTypography.titleLarge.merge(
        TextStyle(fontFamily = GoogleSansFlex, fontWeight = FontWeight.SemiBold),
    ),
    titleMedium = BaseTypography.titleMedium.merge(
        TextStyle(fontFamily = GoogleSansFlex, fontWeight = FontWeight.Medium),
    ),
    bodyLarge = BaseTypography.bodyLarge.merge(TextStyle(fontFamily = GoogleSansFlex)),
    bodyMedium = BaseTypography.bodyMedium.merge(TextStyle(fontFamily = GoogleSansFlex)),
    bodySmall = BaseTypography.bodySmall.merge(TextStyle(fontFamily = GoogleSansFlex)),
    labelLarge = BaseTypography.labelLarge.merge(
        TextStyle(fontFamily = GoogleSansFlex, fontWeight = FontWeight.SemiBold),
    ),
)

@Composable
fun TrackyTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val colorScheme = when {
        dynamicColor -> if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> TrackyDarkColors
        else -> TrackyLightColors
    }
    MaterialExpressiveTheme(
        colorScheme = colorScheme,
        motionScheme = MotionScheme.expressive(),
        shapes = TrackyShapes,
        typography = TrackyTypography,
        content = content,
    )
}
