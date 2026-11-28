import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const TOP_BAR_HEIGHT = 48;
const RIGHT_BTN_MARGIN = 140;
const DRAG_THRESHOLD = 14;

export default class J716FTouchDragExtension extends Extension {
    enable() {
        this._seq = null;
        this._win = null;
        this._dragging = false;
        this._startX = 0;
        this._startY = 0;
        this._winX = 0;
        this._winY = 0;
        this._wasMaximized = false;

        this._handlerId = global.stage.connect('captured-event', (_actor, event) => {
            return this._onEvent(event);
        });
    }

    disable() {
        if (this._handlerId) {
            global.stage.disconnect(this._handlerId);
            this._handlerId = 0;
        }
        this._reset();
    }

    _reset() {
        this._seq = null;
        this._win = null;
        this._dragging = false;
        this._wasMaximized = false;
    }

    _findTopWindowAt(x, y) {
        const actors = global.get_window_actors();
        for (let i = actors.length - 1; i >= 0; i--) {
            const actor = actors[i];
            if (!actor.visible)
                continue;
            const win = actor.meta_window;
            if (!win || win.minimized || win.is_fullscreen())
                continue;
            if (win.get_window_type() !== Meta.WindowType.NORMAL &&
                win.get_window_type() !== Meta.WindowType.DIALOG)
                continue;
            const rect = win.get_frame_rect();
            if (x >= rect.x && x <= rect.x + rect.width &&
                y >= rect.y && y <= rect.y + rect.height) {
                return { win, rect };
            }
        }
        return null;
    }

    _onEvent(event) {
        const type = event.type();
        if (type !== Clutter.EventType.TOUCH_BEGIN &&
            type !== Clutter.EventType.TOUCH_UPDATE &&
            type !== Clutter.EventType.TOUCH_END &&
            type !== Clutter.EventType.TOUCH_CANCEL) {
            return Clutter.EVENT_PROPAGATE;
        }

        const seq = event.get_event_sequence();

        if (type === Clutter.EventType.TOUCH_BEGIN) {
            // Only track a single finger; cancel if second finger touches
            if (this._seq !== null) {
                this._reset();
                return Clutter.EVENT_PROPAGATE;
            }
            if (global.display.get_grab_op() !== Meta.GrabOp.NONE)
                return Clutter.EVENT_PROPAGATE;

            const [x, y] = event.get_coords();
            const hit = this._findTopWindowAt(x, y);
            if (!hit)
                return Clutter.EVENT_PROPAGATE;

            const { win, rect } = hit;
            const relX = x - rect.x;
            const relY = y - rect.y;

            // Only engage inside the top titlebar strip, avoiding right-side window buttons
            if (relY < 0 || relY > TOP_BAR_HEIGHT)
                return Clutter.EVENT_PROPAGATE;
            if (relX > rect.width - RIGHT_BTN_MARGIN)
                return Clutter.EVENT_PROPAGATE;

            this._seq = seq;
            this._win = win;
            this._dragging = false;
            this._startX = x;
            this._startY = y;
            this._winX = rect.x;
            this._winY = rect.y;
            this._wasMaximized = (win.get_maximized() !== 0);
            return Clutter.EVENT_PROPAGATE;
        }

        if (this._seq === null || seq !== this._seq || !this._win)
            return Clutter.EVENT_PROPAGATE;

        if (type === Clutter.EventType.TOUCH_END || type === Clutter.EventType.TOUCH_CANCEL) {
            const wasDragging = this._dragging;
            this._reset();
            return wasDragging ? Clutter.EVENT_STOP : Clutter.EVENT_PROPAGATE;
        }

        // TOUCH_UPDATE
        // If Mutter already started a native drag/resize grab, yield completely
        if (global.display.get_grab_op() !== Meta.GrabOp.NONE) {
            this._reset();
            return Clutter.EVENT_PROPAGATE;
        }

        const [x, y] = event.get_coords();
        const dx = x - this._startX;
        const dy = y - this._startY;

        if (!this._dragging) {
            if (Math.hypot(dx, dy) < DRAG_THRESHOLD)
                return Clutter.EVENT_PROPAGATE;

            // If maximized, require downward drag > 20px to unmaximize first
            if (this._wasMaximized) {
                if (dy < 20)
                    return Clutter.EVENT_PROPAGATE;
                this._win.unmaximize(Meta.MaximizeFlags.BOTH);
                const r = this._win.get_frame_rect();
                this._winX = Math.round(x - r.width / 2);
                this._winY = Math.max(0, Math.round(y - 20));
                this._startX = x;
                this._startY = y;
                this._wasMaximized = false;
            }
            this._win.focus(global.get_current_time());
            this._dragging = true;
        }

        const newX = Math.round(this._winX + (x - this._startX));
        const newY = Math.max(0, Math.round(this._winY + (y - this._startY)));
        this._win.move_frame(true, newX, newY);
        return Clutter.EVENT_STOP;
    }
}
