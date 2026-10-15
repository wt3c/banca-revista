--- Fixed panel zoom: every panel renders at the zoom that fits the page width
--- to the screen, instead of each panel being blown up to fill the screen.
--- Panels that would not fit at that zoom are shrunk just enough to fit.
---
--- The helper's screen is 600x800; the page below is 500x1000, so the fixed
--- zoom is 600 / 500 = 1.2.

local framework = require("tests.PanelsPlusTestFramework")
local describe, it, assert = framework.describe, framework.it, framework.assert

local PanelViewer = require("src._panelviewer")

local PAGE_RECTS = {
    { x = 0, y = 0, w = 500, h = 300 }, -- full page width: fit zoom is already 1.2
    { x = 0, y = 300, w = 250, h = 200 }, -- small: fit zoom 2.4, shown at 1.2
    { x = 250, y = 50, w = 250, h = 900 }, -- tall: fit zoom 0.889 < 1.2, keeps fitting
}

local function newViewer(fields)
    local opts = {
        crop_mode = "strict",
        page = 1,
        image_rects = PAGE_RECTS,
        panel_is_full_page = { false, false, false },
        _images_list_cur = 1,
        reader_ui = {
            document = {
                getNativePageDimensions = function()
                    return { w = 500, h = 1000 }
                end,
            },
        },
    }
    for k, v in pairs(fields or {}) do
        opts[k] = v
    end
    return PanelViewer:new(opts)
end

describe("PanelViewer fixed panel zoom", function()
    it("does not shrink a panel whose fit zoom already equals the page-width zoom", function()
        assert.is_nil(newViewer():getPanelShrinkFactor(1))
    end)

    it("shrinks a small panel down to the page-width zoom", function()
        assert.near(0.5, newViewer():getPanelShrinkFactor(2), 0.0001)
    end)

    it("keeps fitting a panel too big for the page-width zoom", function()
        assert.is_nil(newViewer():getPanelShrinkFactor(3))
    end)

    it("uses the current panel for the displayed image", function()
        local viewer = newViewer({ _images_list_cur = 2 })
        assert.near(0.5, viewer:getMarginShrinkFactor(), 0.0001)
    end)

    it("combines with margin crop mode", function()
        local viewer = newViewer({ crop_mode = "margin", margin_ratio = 0.2 })
        assert.near(0.4, viewer:getPanelShrinkFactor(2), 0.0001)
        assert.near(0.8, viewer:getPanelShrinkFactor(1), 0.0001)
    end)

    it("uses an explicit rect and page for an adjacent page's landing panel", function()
        local viewer = newViewer()
        assert.near(0.5, viewer:getPanelShrinkFactor(nil, false, PAGE_RECTS[2], 2), 0.0001)
    end)

    it("is disabled in no-crop mode, whose images are already screen-sized canvases", function()
        assert.is_nil(newViewer({ crop_mode = "none" }):getPanelShrinkFactor(2))
    end)

    it("is disabled when page dimensions are unavailable", function()
        assert.is_nil(newViewer({ reader_ui = { document = {} } }):getPanelShrinkFactor(2))
        assert.is_nil(newViewer({ reader_ui = false }):getPanelShrinkFactor(2))
    end)
end)
