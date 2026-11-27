// The app's icons: line drawings on a 16 px grid in the colour of the text around them, square
// ends like the rest of the design. An icon never stands alone: the button that carries it has
// a name (aria-label) and a tooltip (ui.js ic()).

const PATHS = {
    bell: 'M4 11V7a4 4 0 0 1 8 0v4l1.5 1.5h-11zM6.5 14.5h3',
    search: 'M7 12A5 5 0 1 0 7 2a5 5 0 0 0 0 10zM10.8 10.8l3.7 3.7',
    sidebar: 'M2 3h12v10H2zM6 3v10',
    edit: 'M3 13h3l7-7-3-3-7 7zM9 4l3 3',
    calendar: 'M2 4h12v10H2zM2 7h12M5 2v3M11 2v3',
    settings: 'M2 5h7M12 5h2M2 11h2M7 11h7M9 3.5h3v3H9zM4 9.5h3v3H4z',
    timeline: 'M2 4h7M5 8h9M3 12h6',
    context: 'M2 4h12M2 8h12M2 12h8',
    terminal: 'M2 3h12v10H2zM4.5 6.5 7 8 4.5 9.5M8.5 10h3',
    browser: 'M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2zM2 8h12M8 2c-2.2 2-2.2 10 0 12M8 2c2.2 2 2.2 10 0 12',
    files: 'M2 4h4.5L8 5.5h6V13H2z',
    changes: 'M8 2v6M5 5h6M5 12h6',
    send: 'M8 13V3M4 7l4-4 4 4',
    plus: 'M8 3v10M3 8h10',
    more: 'M3.5 8h.01M8 8h.01M12.5 8h.01',
    pin: 'M6 2h4l-.5 5L12 9H4l2.5-2zM8 9v5',
    archive: 'M2 3h12v3H2zM3 6v7h10V6M6.5 9h3',
    trash: 'M3 4h10M6 4V2.5h4V4M4.5 4 5 13.5h6L11.5 4M6.8 6.5v5M9.2 6.5v5',
    copy: 'M5.5 5.5h8v8h-8zM3 10.5h-.5v-8h8V3',
    close: 'M3.5 3.5l9 9M12.5 3.5l-9 9',
    check: 'M3 8.5l3.2 3.2L13 5',
    retry: 'M13 8a5 5 0 1 1-1.5-3.5M13 2.5v3h-3',
    down: 'M4 6l4 4 4-4',
    up: 'M4 10l4-4 4 4',
    right: 'M6 4l4 4-4 4',
    left: 'M10 4l-4 4 4 4',
    latest: 'M8 3v10M4 9l4 4 4-4',
    menu: 'M2 4h12M2 8h12M2 12h12',
    shield: 'M8 2l5 2v4c0 3-2 5-5 6-3-1-5-3-5-6V4z',
    keyboard: 'M1.5 4h13v8h-13zM4 7h.01M6.7 7h.01M9.3 7h.01M12 7h.01M5 9.5h6',
    clock: 'M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2zM8 5v3l2 2',
    play: 'M5 3l8 5-8 5z',
    log: 'M4 2h6l3 3v9H4zM6 8h5M6 11h5',
    model: 'M8 2l1.6 4.4L14 8l-4.4 1.6L8 14l-1.6-4.4L2 8l4.4-1.6z',
    folder: 'M2 4h4.5L8 5.5h6V13H2z',
    file: 'M4 2h6l3 3v9H4zM10 2v3h3',
    image: 'M2 3h12v10H2zM2 11l3.5-3.5 3 3 2-2L14 12M10.5 6h.01',
    alert: 'M8 2.5l6 11H2zM8 7v3M8 12h.01',
    command: 'M3 6l3 2-3 2M8 11h5',
    sliders: 'M2 4h3M9 4h5M5 2.5v3h4v-3zM2 12h6M12 12h2M8 10.5v3h4v-3z',
    folderPlus: 'M2 4h4.5L8 5.5h6V13H2zM8 7.5v3M6.5 9h3',
    external: 'M9 3h4v4M13 3l-5 5M6 4H3v9h9v-3',
    branch: 'M5 3v10M5 10c0-2 6-2 6-5M5 3a1.2 1.2 0 1 0 0 .01M5 13a1.2 1.2 0 1 0 0 .01M11 5a1.2 1.2 0 1 0 0 .01',
    plan: 'M3 4h10M3 8h7M3 12h5M11 11l1.5 1.5L15 9.5',
    rewind: 'M4.5 6.5h5.5a3.5 3.5 0 1 1 0 7H6.5M4.5 6.5L7 4M4.5 6.5L7 9',
    bolt: 'M9 1.5L3.5 9H8l-1 5.5L12.5 7H8z',
    server: 'M2.5 3h11v4h-11zM2.5 9h11v4h-11zM5 5h.01M5 11h.01',
    arrowLeft: 'M12.5 8H3.5M7 4.5L3.5 8L7 11.5',
    arrowRight: 'M3.5 8h9M9 4.5L12.5 8L9 11.5',
    overview: 'M2 3h12v10H2zM10 3v10',
    plugins: 'M6 2v3M10 2v3M4 5h8v3a4 4 0 0 1-8 0zM8 12v2',
    pr: 'M5 3v10M11 6v7M5 3a1.2 1.2 0 1 0 0 .01M5 13a1.2 1.2 0 1 0 0 .01M11 13a1.2 1.2 0 1 0 0 .01M8.5 3.5L11 6l-2.5 2.5',
}

// stop is the one filled shape: the square of a transport control
const FILLED = { stop: 'M4 4h8v8H4z' }

export function icon(name, size = 16) {
    const filled = FILLED[name]
    const d = filled || PATHS[name] || ''
    return `<svg class="i" viewBox="0 0 16 16" width="${size}" height="${size}" aria-hidden="true" focusable="false"`
        + (filled ? ` fill="currentColor" stroke="none"` : ` fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="square" stroke-linejoin="miter"`)
        + `><path d="${d}"/></svg>`
}
