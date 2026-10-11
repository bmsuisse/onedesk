<?php

namespace App\Misc;

use Illuminate\Filesystem\Filesystem;

/**
 * Minimal replacement for chumper/zipper (ZipArchive based).
 * Extraction is hardened against Zip Slip:
 * https://github.com/freescout-help-desk/freescout/security/advisories/GHSA-rw7g-qq32-c669
 */
class Zipper
{
    protected $file;
    protected $zip;
    protected $folder = '';

    public function __construct(?Filesystem $file = null)
    {
        $this->file = $file ?: new Filesystem();
    }

    public function __destruct()
    {
        $this->close();
    }

    /**
     * Create a new archive or open an existing one.
     */
    public function make($pathToFile)
    {
        $this->close();

        $dir = dirname($pathToFile);
        if (!is_dir($dir) && !@mkdir($dir, 0755, true) && !is_dir($dir)) {
            throw new \RuntimeException('Zipper: Failed to create directory '.$dir);
        }
        if (!is_writable($dir)) {
            throw new \RuntimeException('Zipper: Directory is not writable: '.$dir);
        }

        $zip = new \ZipArchive();
        $flags = $this->file->exists($pathToFile) ? 0 : \ZipArchive::CREATE;

        if (($code = $zip->open($pathToFile, $flags)) !== true) {
            throw new \RuntimeException('Zipper: Error opening archive '.$pathToFile.' (code '.$code.')');
        }
        $this->zip = $zip;
        $this->folder = '';

        return $this;
    }

    /**
     * Set the folder inside the archive new files are added to.
     */
    public function folder($folder)
    {
        $this->folder = trim(str_replace('\\', '/', (string) $folder), '/');

        return $this;
    }

    /**
     * Add file(s) or directories (recursively) to the archive.
     */
    public function add($pathToAdd, $fileName = null)
    {
        if (is_array($pathToAdd)) {
            foreach ($pathToAdd as $key => $path) {
                $this->add($path, is_int($key) ? null : $key);
            }
        } elseif ($this->file->isFile($pathToAdd)) {
            $this->zip->addFile($pathToAdd, $this->entryName($fileName ?: basename($pathToAdd)));
        } elseif ($this->file->isDirectory($pathToAdd)) {
            $root = rtrim($pathToAdd, '/\\');
            // Like chumper addDir: contents go into the current folder, without the directory's own name.
            foreach ($this->file->allFiles($root, true) as $file) {
                $relative = str_replace('\\', '/', substr($file->getPathname(), strlen($root) + 1));
                $this->zip->addFile($file->getPathname(), $this->entryName($relative));
            }
        }

        return $this;
    }

    protected function entryName($name)
    {
        $name = ltrim(str_replace('\\', '/', $name), '/');

        return $this->folder !== '' ? $this->folder.'/'.$name : $name;
    }

    public function close()
    {
        if ($this->zip) {
            $this->zip->close();
            $this->zip = null;
        }
    }

    /**
     * Extract the whole archive to $path.
     */
    public function extractTo($path)
    {
        if (!$this->file->exists($path) && !$this->file->makeDirectory($path, 0755, true)) {
            throw new \RuntimeException('Zipper: Failed to create folder');
        }

        for ($i = 0; $i < $this->zip->numFiles; $i++) {
            $this->extractEntry($path, $i);
        }
    }

    protected function extractEntry($path, $index)
    {
        $fileName = $this->zip->getNameIndex($index);

        // Prevent Zip traversal attacks.
        if (strpos($fileName, '../') !== false || strpos($fileName, '..\\') !== false) {
            \Log::error('[Zipper] Path traversal detected - special characters found within filename: '.$fileName);
            throw new \RuntimeException('Zipper: Path traversal detected - special characters found within filename');
        }

        $toPath = $path.DIRECTORY_SEPARATOR.$fileName;

        // Directory entry.
        if (substr($fileName, -1) === '/') {
            $this->ensureDirectory($path, $toPath);

            return;
        }

        $dir = pathinfo($toPath, PATHINFO_DIRNAME);
        $this->ensureDirectory($path, $dir);

        // Unsafe symlink: the entry content is the link target.
        if ($this->isSymlinkEntry($index)) {
            $link_target = (string) $this->zip->getFromIndex($index);
            $resolved = ($link_target !== '' && $link_target[0] === '/') ? $link_target : $dir.DIRECTORY_SEPARATOR.$link_target;
            if (!$this->isInside(realpath($path), $this->normalize($resolved))) {
                $msg = '[Zipper] Unsafe symlink detected - symlink '.$fileName.' points to the file/folder outside of the destination path: '.$link_target;
                \Log::error($msg);
                throw new \RuntimeException($msg);
            }
        }

        $stream = $this->zip->getStream($fileName);
        if (!$stream) {
            throw new \RuntimeException('Zipper: Failed to read '.$fileName);
        }
        // Written as a regular file, symlinks are never created.
        $this->file->put($toPath, stream_get_contents($stream));
        fclose($stream);
    }

    /**
     * Create the directory and make sure it resolves inside $path.
     */
    protected function ensureDirectory($path, $dir)
    {
        if (!$this->file->exists($dir) && !$this->file->makeDirectory($dir, 0755, true, true)) {
            throw new \RuntimeException('Zipper: Failed to create folders');
        }
        $realBase = realpath($path);
        $realDest = realpath($dir);
        if ($realBase && $realDest && !$this->isInside($realBase, $realDest)) {
            \Log::error('[Zipper] Path traversal detected - path: '.$path.'; dir: '.$dir.'; realDest: '.$realDest);
            throw new \RuntimeException('Zipper: Path traversal detected');
        }
    }

    protected function isInside($base, $target)
    {
        return $target === $base || strpos($target, rtrim($base, '/\\').DIRECTORY_SEPARATOR) === 0;
    }

    protected function normalize($path)
    {
        $parts = [];
        foreach (explode('/', str_replace('\\', '/', $path)) as $part) {
            if ($part === '..') {
                array_pop($parts);
            } elseif ($part !== '' && $part !== '.') {
                $parts[] = $part;
            }
        }

        return '/'.implode('/', $parts);
    }

    protected function isSymlinkEntry($index)
    {
        $opsys = null;
        $attr = null;
        if (!$this->zip->getExternalAttributesIndex($index, $opsys, $attr)) {
            return false;
        }

        return $opsys === \ZipArchive::OPSYS_UNIX && (($attr >> 16) & 0170000) === 0120000;
    }
}
