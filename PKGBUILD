# Maintainer: TU NOMBRE <tu@correo>
pkgname=gastli
pkgver=1.0.0
pkgrel=1
pkgdesc="Sistema de finanzas personales en terminal (TUI) con exportación a Excel"
arch=('any')
url="https://github.com/LeonardoVenus/gastli"
license=('MIT')
depends=('python')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP') # reemplázalo corriendo: updpkgsums

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
