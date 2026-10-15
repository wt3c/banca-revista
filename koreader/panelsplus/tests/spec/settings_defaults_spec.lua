--- Default settings for a fresh install.

local framework = require("tests.PanelsPlusTestFramework")
local describe, it, assert = framework.describe, framework.it, framework.assert

local Settings = require("src._settings")

describe("Panels+ default settings", function()
    it("reads panels left to right (comic) by default", function()
        assert.equals("comic", Settings.defaults.mode)
    end)
end)
