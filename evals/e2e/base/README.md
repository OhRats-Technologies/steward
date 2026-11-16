# Tally

Tally is a small command-line tool that counts words, lines and characters in text files.
It reads one or more files, or standard input when no file is given, and prints one line per
file followed by a total.

## Install

Download the single binary for your platform from the releases page and put it on your PATH.
No runtime or configuration file is needed.

## Usage

Run `tally notes.txt` to count one file, or `tally *.md` to count several. Use `--words`,
`--lines` or `--chars` to print only one column. The exit code is zero on success and one when
a file cannot be read.

## License

MIT.
