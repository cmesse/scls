Name:           scls-release
Version:        2026
Release:        2%{?dist}
Summary:        SCLS repository configuration and GPG key

License:        BSD-3-Clause-LBNL
URL:            https://belfem.lbl.gov/scls

Source0:        scls.repo
Source1:        RPM-GPG-KEY-SCLS

BuildArch:      noarch

# Pick the published-repo subdirectory based on the build host. Each
# supported distro publishes its own tree because dist-tagged RPMs are
# ABI-incompatible across distros (.el9 vs .el10 vs .amzn2023).
%global scls_repo_dir %{nil}
%if 0%{?rhel}
%global scls_repo_dir el%{rhel}
%endif
%if 0%{?amzn}
%global scls_repo_dir amzn%{amzn}
%endif
%if "%{scls_repo_dir}" == ""
%{error:scls-release: cannot determine target distro (neither %%{rhel} nor %%{amzn} is set)}
%endif

%description
This package provides the repository configuration and GPG key
for the Scientific Core Library Stack (SCLS).

%install
install -Dpm 644 %{SOURCE0} %{buildroot}/etc/yum.repos.d/scls.repo
sed -i 's|@SCLS_REPO_DIR@|%{scls_repo_dir}|g' %{buildroot}/etc/yum.repos.d/scls.repo
install -Dpm 644 %{SOURCE1} %{buildroot}/etc/pki/rpm-gpg/RPM-GPG-KEY-SCLS

%files
/etc/yum.repos.d/scls.repo
/etc/pki/rpm-gpg/RPM-GPG-KEY-SCLS

%changelog
* Tue May 05 2026 Christian Messe <christian.messe@gmail.com> - 2026-2
- Make scls.repo baseurl distro-aware so the package works on
  Enterprise Linux 9, Enterprise Linux 10, and Amazon Linux 2023.

* Sat Apr 18 2026 Christian Messe <christian.messe@gmail.com> - 2026-1
- Initial scls-release package: ships scls.repo and RPM-GPG-KEY-SCLS.
