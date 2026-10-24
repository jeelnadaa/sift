package com.solarquack.sift.data

import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow

/** "Something changed": read on another device or in Gmail, new mail, filing. Sent by the server
 * as a silent push ({"type": "sync"}), and when the app comes back to the screen. Screens that
 * show mail collect `changes` and reload quietly (data stays on screen while it loads). */
object LiveEvents {
    private val flow = MutableSharedFlow<Unit>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val changes: SharedFlow<Unit> = flow

    fun changed() { flow.tryEmit(Unit) }
}
