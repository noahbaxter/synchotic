-- Single-purpose host config for Synchotic.
-- Synchotic paints its own truecolor UI, so colors here are only window chrome.
local wezterm = require 'wezterm'
local config = wezterm.config_builder()

-- Synchotic's screens are laid out for 80-120 columns and the menus want room
-- to breathe, so start wide enough that nothing truncates. WezTerm has no size
-- persistence of its own; save on resize and read it back at startup.
local DEFAULT_COLS, DEFAULT_ROWS = 100, 34

-- The launcher hands us the OS data dir for this platform; it is the only side
-- that can work one out. Falls back to the macOS location for a stale host
-- config left behind by an older launcher.
local function size_file()
  return os.getenv('SYNCHOTIC_WINDOW_FILE')
      or ((os.getenv('HOME') or '.') .. '/Library/Application Support/Synchotic/window.txt')
end

local cols, rows = DEFAULT_COLS, DEFAULT_ROWS
do
  local f = io.open(size_file(), 'r')
  if f then
    local c = tonumber(f:read('l') or '')
    local r = tonumber(f:read('l') or '')
    f:close()
    -- guard against a corrupt or absurd saved value
    if c and r and c >= 70 and c <= 400 and r >= 20 and r <= 200 then
      cols, rows = c, r
    end
  end
end
config.initial_cols = cols
config.initial_rows = rows

wezterm.on('window-resized', function(_window, pane)
  local dims = pane:get_dimensions()
  local path = size_file()
  os.execute('mkdir -p "' .. path:gsub('/[^/]*$', '') .. '"')
  local f = io.open(path, 'w')
  if f then
    f:write(tostring(dims.cols) .. '\n' .. tostring(dims.viewport_rows) .. '\n')
    f:close()
  end
end)

config.enable_tab_bar = false
config.window_close_confirmation = 'NeverPrompt'
config.exit_behavior = 'Close'
config.window_padding = { left = '1cell', right = '1cell', top = '0.5cell', bottom = '0.5cell' }

-- MUST stay 12.0: any other size triggers WezTerm's window-doubling bug on
-- non-Retina external monitors (wezterm/wezterm#4851), which blows initial_cols
-- and initial_rows up to roughly 2x and ignores the intended size.
config.font_size = 12.0

-- WebGpu on Windows. The default OpenGL front end needs a GPU driver with
-- OpenGL 3.3, so a machine without one (a VM, an old laptop, some remote
-- sessions) got "The OpenGL implementation is too old to work with glium" and
-- no window at all. 'Software' still goes through OpenGL there and fails the
-- same way. WebGpu runs on Direct3D, which falls back to its own software
-- renderer, and opened on a Windows 11 VM with no GPU where both others died.
if wezterm.target_triple:find('windows') then
  config.front_end = 'WebGpu'
end

-- WezTerm only pastes on Ctrl+Shift+V, so Ctrl+V and right-click did nothing
-- for people used to the Windows console. Both add to the defaults. Not on
-- macOS, where Cmd+V already pastes and Ctrl+V belongs to the app.
if not wezterm.target_triple:find('darwin') then
  local act = wezterm.action
  config.keys = {
    { key = 'v', mods = 'CTRL', action = act.PasteFrom 'Clipboard' },
  }
  config.mouse_bindings = {
    { event = { Down = { streak = 1, button = 'Right' } }, mods = 'NONE',
      action = act.PasteFrom 'Clipboard' },
  }
end

config.colors = {
  foreground = '#dcd7ba',
  background = '#1f1f28',
  cursor_bg  = '#c8c093',
  cursor_fg  = '#1f1f28',
}

return config
