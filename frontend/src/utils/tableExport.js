/**
 * File exports for the print screen.
 *
 * The screen builds one rectangular table — a header row and a list of rows —
 * and hands the very same matrix to every format, so what leaves as a
 * spreadsheet is what the A4 sheet shows. Both writers are here rather than in
 * a dependency: an .xlsx is a zip of six short XML parts, and pulling a
 * spreadsheet library into the bundle to write them is a poor trade.
 */

const encoder = new TextEncoder();

/* ---------------------------------------------------------------- download */

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking straight away cancels the download in some browsers; one tick is
  // enough for every one of them to have started reading the blob.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

/* --------------------------------------------------------------------- csv */

/**
 * Semicolon-separated and prefixed with a byte-order mark, which is what makes
 * Excel open it as UTF-8 with the columns already split — a comma-separated
 * file lands in a single column on a machine set to Slovak.
 */
export function downloadCsv(filename, header, rows) {
  const escape = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const lines = [header, ...rows].map((row) => row.map(escape).join(';'));
  const blob = new Blob(['\uFEFF' + lines.join('\r\n') + '\r\n'], {
    type: 'text/csv;charset=utf-8',
  });
  saveBlob(blob, filename);
}

/* --------------------------------------------------------------------- zip */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

const crc32 = (bytes) => {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
};

/** 1980-01-01 in the DOS field the zip format stores timestamps in. */
const DOS_DATE = 0x21;

/**
 * Zip archive of UTF-8 text parts, stored rather than deflated. A workbook of
 * one month is a few dozen kilobytes of XML and the browser offers no
 * synchronous deflate, so the size is worth not having a compression step.
 */
const zipParts = (parts) => {
  const chunks = [];
  const directory = [];
  let offset = 0;

  parts.forEach(({ name, text }) => {
    const nameBytes = encoder.encode(name);
    const data = encoder.encode(text);
    const crc = crc32(data);

    const local = new Uint8Array(30 + nameBytes.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true); // version needed
    lv.setUint16(6, 0x0800, true); // names are UTF-8
    lv.setUint16(8, 0, true); // stored, not deflated
    lv.setUint16(10, 0, true); // time
    lv.setUint16(12, DOS_DATE, true);
    lv.setUint32(14, crc, true);
    lv.setUint32(18, data.length, true);
    lv.setUint32(22, data.length, true);
    lv.setUint16(26, nameBytes.length, true);
    local.set(nameBytes, 30);

    const entry = new Uint8Array(46 + nameBytes.length);
    const ev = new DataView(entry.buffer);
    ev.setUint32(0, 0x02014b50, true);
    ev.setUint16(4, 20, true); // version made by
    ev.setUint16(6, 20, true); // version needed
    ev.setUint16(8, 0x0800, true);
    ev.setUint16(10, 0, true);
    ev.setUint16(12, 0, true);
    ev.setUint16(14, DOS_DATE, true);
    ev.setUint32(16, crc, true);
    ev.setUint32(20, data.length, true);
    ev.setUint32(24, data.length, true);
    ev.setUint16(28, nameBytes.length, true);
    ev.setUint32(42, offset, true);
    entry.set(nameBytes, 46);

    chunks.push(local, data);
    directory.push(entry);
    offset += local.length + data.length;
  });

  const directorySize = directory.reduce((sum, entry) => sum + entry.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(8, parts.length, true);
  endView.setUint16(10, parts.length, true);
  endView.setUint32(12, directorySize, true);
  endView.setUint32(16, offset, true);

  return new Blob([...chunks, ...directory, end], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
};

/* -------------------------------------------------------------------- xlsx */

/* XML 1.0 has no way of carrying a control character at all, not even
   escaped, so anything under a space that is not a tab or a line break
   is dropped rather than encoded. */
const stripControls = (text) => {
  let kept = '';
  for (const char of text) {
    const code = char.codePointAt(0);
    if (code > 0x1f || code === 0x09 || code === 0x0a || code === 0x0d) {
      kept += char;
    }
  }
  return kept;
};

const xmlEscape = (value) =>
  stripControls(String(value ?? ''))
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

/** 0 -> "A", 25 -> "Z", 26 -> "AA". A month of columns needs the second letter. */
const columnName = (index) => {
  let name = '';
  let n = index;
  do {
    name = String.fromCharCode(65 + (n % 26)) + name;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return name;
};

const cellXml = (value, rowIndex, columnIndex, styleId) => {
  const ref = `${columnName(columnIndex)}${rowIndex}`;
  const text = String(value ?? '');
  if (!text) return `<c r="${ref}" s="${styleId}"/>`;
  return (
    `<c r="${ref}" s="${styleId}" t="inlineStr">` +
    `<is><t xml:space="preserve">${xmlEscape(text)}</t></is></c>`
  );
};

const CONTENT_TYPES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`;

const ROOT_RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`;

const WORKBOOK_RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`;

/* Style 0 wraps and sits at the top of its cell, style 1 is the same in bold
   for the header row and the date column, style 2 is the shading a weekend or
   a day of rest gets. Nothing else is used, so nothing else is defined. */
const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="10"/><name val="Calibri"/></font><font><b/><sz val="10"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFEDEDED"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right><top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;

/** Excel refuses a sheet name over 31 characters or holding []:*?/\ */
const sheetName = (name) =>
  (name || 'Rozvrh').replace(/[[\]:*?/\\]/g, ' ').slice(0, 31) || 'Rozvrh';

/**
 * Write one sheet as a real .xlsx.
 *
 * `header` is the first row of the table, `rows` the rest. `highlighted` holds
 * indexes into `rows` that are shaded — the same weekends and days of rest the
 * printed sheet greys out. `widths` are per column, in Excel's character unit.
 */
export function downloadXlsx(filename, name, header, rows, options = {}) {
  const { highlighted = new Set(), widths = [], title = null } = options;

  const lines = [];
  let cursor = 1;

  if (title) {
    lines.push(`<row r="${cursor}">${cellXml(title, cursor, 0, 1)}</row>`);
    // The caption, then a blank row, so the table below still reads as a table
    // to Excel's own sort and filter.
    cursor += 2;
  }

  const headerRow = cursor;
  lines.push(
    `<row r="${headerRow}">` +
      header.map((value, index) => cellXml(value, headerRow, index, 1)).join('') +
      '</row>'
  );

  rows.forEach((row, index) => {
    const r = headerRow + 1 + index;
    const style = highlighted.has(index) ? 2 : 0;
    lines.push(
      `<row r="${r}">` +
        row
          .map((value, column) => cellXml(value, r, column, column === 0 ? 1 : style))
          .join('') +
        '</row>'
    );
  });

  const cols = widths.length
    ? `<cols>${widths
        .map(
          (width, index) =>
            `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`
        )
        .join('')}</cols>`
    : '';

  const sheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0"><pane ySplit="${headerRow}" topLeftCell="A${headerRow + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
${cols}<sheetData>${lines.join('')}</sheetData>
<pageMargins left="0.3" right="0.3" top="0.4" bottom="0.4" header="0.3" footer="0.3"/>
</worksheet>`;

  const workbook = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="${xmlEscape(sheetName(name))}" sheetId="1" r:id="rId1"/></sheets>
</workbook>`;

  saveBlob(
    zipParts([
      { name: '[Content_Types].xml', text: CONTENT_TYPES },
      { name: '_rels/.rels', text: ROOT_RELS },
      { name: 'xl/workbook.xml', text: workbook },
      { name: 'xl/_rels/workbook.xml.rels', text: WORKBOOK_RELS },
      { name: 'xl/styles.xml', text: STYLES },
      { name: 'xl/worksheets/sheet1.xml', text: sheet },
    ]),
    filename
  );
}
