# Release checklist

Replace `X.Y.Z` with the new version.

## 1. Prepare
- [ ] `VERSION` in `cutline` and `pkgver` in `packaging/arch/PKGBUILD` are `X.Y.Z` (and `pkgrel=1`).
- [ ] `CHANGELOG.md`: move *Unreleased* into `## [X.Y.Z] - YYYY-MM-DD` and update the compare links.
- [ ] `./cutline --version` prints `cutline X.Y.Z`.

## 2. Test
- [ ] CI is green on `main` (tests, security scan, Arch package).
- [ ] `./install --link`, launch from the app launcher, open an existing project.
- [ ] New project from a video, split, ripple delete, add a second video as picture-in-picture.
- [ ] Export at original size and at 1080p, and play the result (`mpv <file>`).
- [ ] If you have one, an HDR (iPhone) clip looks natural in the preview and in the export.
- [ ] Packaging: `cd packaging/arch && makepkg -f && namcap PKGBUILD *.pkg.tar.zst` (after step 3, with the tag pushed).

## 3. Tag and publish (only when the repo is meant to be public)
```sh
git commit -am "Release vX.Y.Z"
git tag -a vX.Y.Z -m "Cutline X.Y.Z"
git push origin main --follow-tags
gh release create vX.Y.Z --title "Cutline X.Y.Z" --notes "See CHANGELOG.md"
```

## 4. AUR

### First time only
1. Make an account at https://aur.archlinux.org/register.
2. Make a key just for the AUR and add its public half under *My Account → SSH Public Key*:
   ```sh
   ssh-keygen -t ed25519 -f ~/.ssh/aur -C "aur"
   cat ~/.ssh/aur.pub
   ```
3. Tell ssh to use it:
   ```sh
   printf 'Host aur.archlinux.org\n  IdentityFile ~/.ssh/aur\n  User aur\n' >> ~/.ssh/config
   ```
4. `git clone ssh://aur@aur.archlinux.org/cutline.git ~/aur/cutline` (an empty repo: the name is free,
   cloning it is how the package is created).

### Every release
```sh
cd packaging/arch
updpkgsums                              # fills sha256sums from the GitHub tarball
makepkg -f && namcap PKGBUILD cutline-*.pkg.tar.zst
makepkg --printsrcinfo > .SRCINFO
git -C ../.. commit -am "PKGBUILD: checksums for vX.Y.Z" && git -C ../.. push

# the AUR package lives in its own git repo:
git clone ssh://aur@aur.archlinux.org/cutline.git ~/aur/cutline   # first time only
cp PKGBUILD .SRCINFO ~/aur/cutline/
cd ~/aur/cutline && git add PKGBUILD .SRCINFO && git commit -m "Update to X.Y.Z" && git push
```
