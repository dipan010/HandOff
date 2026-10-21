// Pictures arrive as base64: small JPEG live frames while a task runs, and
// full-size PNG screenshots when HandOff looks at the page.
export function pictureSrc(base64: string): string {
    const type = base64.startsWith('/9j/') ? 'image/jpeg' : 'image/png';
    return `data:${type};base64,${base64}`;
}
