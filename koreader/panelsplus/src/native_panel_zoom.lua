--- Native panel-zoom integration methods mixed into `PanelsPlus`.
---
--- @class PPNativePanelZoomMethods
local NativePanelZoom = {}

--- Replace KOReader's native panel zoom handler while this plugin is active.
function NativePanelZoom:patchNativePanelZoom()
    local highlight = self.ui.highlight
    if not highlight then
        return
    end
    if highlight._panels_plus_original_panel_zoom then
        -- Already patched (e.g. a second init() without an intervening
        -- onCloseWidget): still refresh the plugin reference so the hook
        -- doesn't keep driving a stale PanelsPlus instance.
        highlight._panels_plus_plugin = self
        return
    end

    highlight._panels_plus_plugin = self
    highlight._panels_plus_original_panel_zoom = highlight.onPanelZoom
    highlight._panels_plus_original_hold = highlight.onHold
    highlight.onPanelZoom = function(reader_highlight, arg, ges)
        local plugin = reader_highlight._panels_plus_plugin
        if plugin and plugin:isEnabled() then
            return plugin:showPanelSequence(reader_highlight, ges)
        end
        return reader_highlight:_panels_plus_original_panel_zoom(arg, ges)
    end
    highlight.onHold = function(reader_highlight, arg, ges)
        local plugin = reader_highlight._panels_plus_plugin
        if plugin and plugin:isEnabled() and plugin:showEmbeddedImagePanels(reader_highlight, ges) then
            return true
        end
        return reader_highlight:_panels_plus_original_hold(arg, ges)
    end
end

--- Gesture-manager double-tap zones the panel trigger must win over (sides
--- default to jumping +/-10 pages); they still fire when no panel is found.
local DOUBLE_TAP_OVERRIDES = {
    "double_tap_left_side",
    "double_tap_right_side",
    "double_tap_top_left_corner",
    "double_tap_top_right_corner",
    "double_tap_bottom_left_corner",
    "double_tap_bottom_right_corner",
}

local DOUBLE_TAP_ZONE = {
    id = "panels_plus_double_tap",
    ges = "double_tap",
    screen_zone = { ratio_x = 0, ratio_y = 0, ratio_w = 1, ratio_h = 1 },
    overrides = DOUBLE_TAP_OVERRIDES,
}

--- Open the panel under a double tap/click, like Kindle's Panel View.
---
--- KOReader only emits `double_tap` when the topmost widget clears
--- `disable_double_tap` (ReaderUI copies the global "Disable double tap"
--- setting, true by default), so the reader opts in here. Trade-off: single
--- taps wait for the double-tap interval before firing.
function NativePanelZoom:registerDoubleTapPanelZoom()
    local ui = self.ui
    if not (ui and ui.paging and ui.registerTouchZones) then
        return
    end
    ui.disable_double_tap = false
    local zone = {}
    for k, v in pairs(DOUBLE_TAP_ZONE) do
        zone[k] = v
    end
    zone.handler = function(ges)
        local highlight = ui.highlight
        if not (highlight and self:isEnabled()) then
            return false
        end
        return highlight:onPanelZoom(nil, ges) and true or false
    end
    ui:registerTouchZones({ zone })
end

--- Remove the double-tap panel trigger registered by `registerDoubleTapPanelZoom`.
function NativePanelZoom:unregisterDoubleTapPanelZoom()
    local ui = self.ui
    if ui and ui.paging and ui.unRegisterTouchZones then
        ui:unRegisterTouchZones({ DOUBLE_TAP_ZONE })
    end
end

--- Keep KOReader panel zoom active so disabling Panels+ focusing falls back to native panel zoom.
function NativePanelZoom:applyNativePanelSetting()
    if self.ui.highlight and self.ui.paging then
        self.ui.highlight.panel_zoom_enabled = true
        self.ui.highlight.panel_zoom_fallback_to_text_selection = false
    end
end

--- KOReader hook: reapply the native panel-zoom override after document load.
---
--- `ReaderHighlight:onReadSettings` only defaults `panel_zoom_enabled` to true
--- for cbz/cbt (false for pdf/cbr) and `panel_zoom_fallback_to_text_selection`
--- to true for pdf, then assigns those onto `self.ui.highlight` from the
--- per-document/per-extension settings. That assignment runs as part of the
--- same `ReadSettings` broadcast that follows plugin init, and since
--- `highlight` is registered before plugins it always runs first -- so it
--- silently overwrites the values `applyNativePanelSetting` set in `init()`,
--- which made pdf/cbr hold gestures fall through to dictionary/OCR lookup
--- instead of ever reaching `onPanelZoom`. Reapplying here, after that
--- broadcast reaches this module, restores the override.
function NativePanelZoom:onReadSettings()
    self:applyNativePanelSetting()
end

--- Restore the original native panel zoom handler.
---
--- Called from `PanelsPlus:onCloseWidget` rather than being one itself: mixin
--- methods are copied by name, so only one module can own that hook.
function NativePanelZoom:restoreNativePanelZoom()
    local highlight = self.ui and self.ui.highlight
    if highlight and highlight._panels_plus_original_panel_zoom then
        highlight.onPanelZoom = highlight._panels_plus_original_panel_zoom
        highlight.onHold = highlight._panels_plus_original_hold
        highlight._panels_plus_original_panel_zoom = nil
        highlight._panels_plus_original_hold = nil
        highlight._panels_plus_plugin = nil
    end
end

return NativePanelZoom
