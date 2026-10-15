--- Regression coverage for the reflow-document hold hook.
local framework = require("tests.PanelsPlusTestFramework")
local describe, it, assert, spy = framework.describe, framework.it, framework.assert, framework.spy

local NativePanelZoom = require("src.native_panel_zoom")

describe("NativePanelZoom embedded-image hold hook", function()
    it("opens Panels+ first and preserves KOReader's image/text fallback", function()
        local native_hold = spy()
        native_hold.return_value = "native"
        local native_zoom = spy()
        local highlight = {
            onHold = native_hold,
            onPanelZoom = native_zoom,
        }
        local plugin = {
            ui = { highlight = highlight },
            enabled = true,
            embedded_result = true,
        }
        function plugin:isEnabled()
            return self.enabled
        end
        function plugin:showEmbeddedImagePanels()
            return self.embedded_result
        end

        NativePanelZoom.patchNativePanelZoom(plugin)
        assert.is_true(highlight:onHold(nil, { pos = {} }))
        assert.equals(0, native_hold:callCount(), "Panels+ should consume a detected embedded image")

        plugin.embedded_result = false
        assert.equals("native", highlight:onHold(nil, { pos = {} }))
        assert.equals(1, native_hold:callCount(), "text and unsupported images must fall back to KOReader")

        NativePanelZoom.restoreNativePanelZoom(plugin)
        assert.equals(native_hold, highlight.onHold)
        assert.equals(native_zoom, highlight.onPanelZoom)
    end)
end)

describe("NativePanelZoom double-tap trigger", function()
    local function makePlugin(opts)
        local zone_calls = { registered = {}, unregistered = {} }
        local zoom = spy()
        zoom.return_value = opts.zoom_result
        local ui = {
            paging = opts.paging,
            highlight = { onPanelZoom = zoom },
        }
        function ui:registerTouchZones(zones)
            table.insert(zone_calls.registered, zones)
        end
        function ui:unRegisterTouchZones(zones)
            table.insert(zone_calls.unregistered, zones)
        end
        local plugin = { ui = ui, enabled = true }
        function plugin:isEnabled()
            return self.enabled
        end
        return plugin, zone_calls, zoom
    end

    it("registers a full-screen double_tap zone that opens the tapped panel", function()
        local plugin, zone_calls, zoom = makePlugin({ paging = {}, zoom_result = true })

        NativePanelZoom.registerDoubleTapPanelZoom(plugin)

        assert.equals(false, plugin.ui.disable_double_tap, "reader must emit double_tap gestures")
        assert.equals(1, #zone_calls.registered)
        local zone = zone_calls.registered[1][1]
        assert.equals("double_tap", zone.ges)
        assert.equals(1, zone.screen_zone.ratio_w)
        assert.equals(1, zone.screen_zone.ratio_h)
        local overridden = {}
        for _, id in ipairs(zone.overrides) do
            overridden[id] = true
        end
        assert.is_true(overridden.double_tap_left_side, "must win over the default -10 pages jump")
        assert.is_true(overridden.double_tap_right_side, "must win over the default +10 pages jump")

        local ges = { pos = { x = 10, y = 20 } }
        assert.is_true(zone.handler(ges))
        assert.equals(1, zoom:callCount())
    end)

    it("falls back to other double-tap gestures when no panel is found or plugin is disabled", function()
        local plugin, zone_calls, zoom = makePlugin({ paging = {}, zoom_result = false })
        NativePanelZoom.registerDoubleTapPanelZoom(plugin)
        local zone = zone_calls.registered[1][1]

        assert.equals(false, zone.handler({ pos = {} }))

        plugin.enabled = false
        assert.equals(false, zone.handler({ pos = {} }))
        assert.equals(1, zoom:callCount(), "disabled plugin must not try to zoom")
    end)

    it("does nothing on reflowable documents", function()
        local plugin, zone_calls = makePlugin({ paging = nil })
        NativePanelZoom.registerDoubleTapPanelZoom(plugin)
        assert.equals(0, #zone_calls.registered)
        assert.equals(nil, plugin.ui.disable_double_tap)
    end)

    it("unregisters the zone on restore", function()
        local plugin, zone_calls = makePlugin({ paging = {}, zoom_result = true })
        NativePanelZoom.registerDoubleTapPanelZoom(plugin)
        NativePanelZoom.unregisterDoubleTapPanelZoom(plugin)
        assert.equals(1, #zone_calls.unregistered)
        assert.equals(zone_calls.registered[1][1].id, zone_calls.unregistered[1][1].id)
    end)
end)
