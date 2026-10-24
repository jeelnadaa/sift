package com.solarquack.sift.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.dp

/** Line icons drawn like the web sidebar's (24 viewport, round caps), tinted by `Icon`. */
object SiftIcons {
    private fun stroke(vararg paths: String): ImageVector {
        val b = ImageVector.Builder(defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f)
        paths.forEach { d ->
            b.addPath(
                pathData = PathParser().parsePathString(d).toNodes(), fill = null, stroke = SolidColor(Color.White),
                strokeLineWidth = 1.7f, strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round,
            )
        }
        return b.build()
    }

    val Feed = stroke(
        "M3 13 L5.5 5.5 A2 2 0 0 1 7.4 4 H16.6 A2 2 0 0 1 18.5 5.5 L21 13 V18 A2 2 0 0 1 19 20 H5 A2 2 0 0 1 3 18 Z",
        "M3 13 H8 L9.5 15.5 H14.5 L16 13 H21",
    )
    val Deals = stroke("M12 3 L20 7.5 V16.5 L12 21 L4 16.5 V7.5 Z", "M12 12 L20 7.5 M12 12 V21 M12 12 L4 7.5")
    val Todo = stroke("M7 4 H17 A3 3 0 0 1 20 7 V17 A3 3 0 0 1 17 20 H7 A3 3 0 0 1 4 17 V7 A3 3 0 0 1 7 4 Z", "M8.5 12.5 L11 15 L15.5 10")
    val More = stroke("M4 7 H20", "M4 12 H20", "M4 17 H20")
    val Pen = stroke("M4 20 L8.5 19 L18.5 9 A2.1 2.1 0 0 0 15.5 6 L5.5 16 L4 20 Z", "M14 7 L17 10")
}
