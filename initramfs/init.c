/*
 * Minimal arm64 initramfs init for vayu (POCO X3 Pro).
 *
 * This is pid 1 of a bringup ramdisk: it mounts the pseudo filesystems a
 * kernel needs to be inspectable, prints the identity of the kernel it is
 * running under, reports any crash log pstore recovered from the previous
 * boot, and then either hands over to a real init or stays alive so the
 * kernel does not panic with "no working init".
 *
 * vayu has no UART, so the console this writes to is ttyMSM0 (the kernel
 * cmdline already says androidboot.console=ttyMSM0) and, on a device that is
 * not booting Android yet, the practical way to read it is to let the kernel
 * log a panic into ramoops and read /sys/fs/pstore on the next boot. That is
 * why mounting pstore and listing what it holds is part of this program
 * rather than a shell script someone has to remember to run.
 *
 * Deliberately small: no libc features beyond file I/O and mount(2), no
 * dynamic linking, no busybox. `init --selftest` exercises everything that
 * does not require being pid 1, so CI can run the same code on the host.
 *
 * Build (CI does this):
 *   aarch64-linux-gnu-gcc -Os -static -Wall -Wextra -o init init.c
 */

#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>

static int verbose = 1;

static void say(const char *fmt, ...)
{
	va_list ap;

	if (!verbose)
		return;
	va_start(ap, fmt);
	vfprintf(stdout, fmt, ap);
	va_end(ap);
	fputc('\n', stdout);
	fflush(stdout);
}

static void try_mount(const char *source, const char *target, const char *type,
		      unsigned long flags)
{
	mkdir(target, 0755);
	if (mount(source, target, type, flags, NULL) == 0) {
		say("mounted %-9s on %s", type, target);
		return;
	}
	say("mount %s on %s: %s", type, target, strerror(errno));
}

static void read_trimmed(const char *path, char *buf, size_t size)
{
	int fd = open(path, O_RDONLY);
	ssize_t got;

	buf[0] = '\0';
	if (fd < 0)
		return;
	got = read(fd, buf, size - 1);
	close(fd);
	if (got <= 0) {
		buf[0] = '\0';
		return;
	}
	buf[got] = '\0';
	while (got > 0 && (buf[got - 1] == '\n' || buf[got - 1] == '\r'))
		buf[--got] = '\0';
}

/* Print the first line of /proc/cmdline; the whole thing does not fit on a
 * phone-width console and the interesting switches are at the front. */
static void show_cmdline(void)
{
	char cmdline[1024];

	read_trimmed("/proc/cmdline", cmdline, sizeof(cmdline));
	if (cmdline[0] == '\0')
		return;
	say("cmdline: %.160s%s", cmdline, strlen(cmdline) > 160 ? "..." : "");
}

static int has_cmdline_word(const char *word)
{
	char cmdline[1024];
	char needle[64];

	snprintf(needle, sizeof(needle), "%s", word);
	read_trimmed("/proc/cmdline", cmdline, sizeof(cmdline));
	return strstr(cmdline, needle) != NULL;
}

/* /sys/fs/pstore holds ramoops records carried across a reset. On a device
 * with no serial console this is the only place a mainline panic survives. */
static void show_pstore(void)
{
	DIR *dir = opendir("/sys/fs/pstore");
	struct dirent *entry;
	int count = 0;

	if (!dir) {
		say("pstore: not mounted (%s)", strerror(errno));
		return;
	}
	while ((entry = readdir(dir)) != NULL) {
		struct stat st;
		char path[512];

		if (entry->d_name[0] == '.')
			continue;
		snprintf(path, sizeof(path), "/sys/fs/pstore/%s", entry->d_name);
		if (stat(path, &st) != 0)
			continue;
		say("pstore: %s (%lld bytes)", entry->d_name,
		    (long long)st.st_size);
		count++;
	}
	closedir(dir);
	if (count == 0)
		say("pstore: empty (no crash recovered from the last boot)");
}

static void show_identity(void)
{
	struct utsname uts;

	if (uname(&uts) == 0)
		say("%s %s %s", uts.sysname, uts.release, uts.machine);
	else
		say("uname failed: %s", strerror(errno));
	show_cmdline();
}

/* Run a program the kernel cmdline asked for, e.g. rd.shell. Returns only on
 * failure, since a successful execve replaces this process. */
static void exec_requested(const char *path)
{
	char *const argv[] = { (char *)path, NULL };
	char *const envp[] = { "PATH=/sbin:/bin:/usr/sbin:/usr/bin", NULL };

	say("handing over to %s", path);
	execve(path, argv, envp);
	say("exec %s: %s", path, strerror(errno));
}

static void reap(int sig)
{
	int status;
	pid_t pid;

	(void)sig;
	while ((pid = waitpid(-1, &status, WNOHANG)) > 0)
		say("child %d exited with status %d", (int)pid, status);
}

int main(int argc, char **argv)
{
	int selftest = 0;
	int i;


	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--selftest") == 0)
			selftest = 1;
		else if (strcmp(argv[i], "--quiet") == 0)
			verbose = 0;
	}

	say("vayu-mainline initramfs");
	show_identity();

	if (selftest) {
		show_pstore();
		say("selftest ok");
		return 0;
	}

	try_mount("proc", "/proc", "proc", 0);
	try_mount("sysfs", "/sys", "sysfs", 0);
	try_mount("devtmpfs", "/dev", "devtmpfs", 0);
	try_mount("devpts", "/dev/pts", "devpts", 0);
	try_mount("tmpfs", "/tmp", "tmpfs", 0);
	/* The kernel registers this mount point itself when PSTORE=y; mounting
	 * it explicitly keeps the layout the same if it ever does not. */
	try_mount("pstore", "/sys/fs/pstore", "pstore", 0);
	show_pstore();

	if (has_cmdline_word("rd.shell")) {
		exec_requested("/bin/sh");
		say("rd.shell requested but there is no /bin/sh in this ramdisk");
	}

	/* Anything another ramdisk put under /sbin gets handed over to, so
	 * this init can sit in front of a richer one later. */
	if (access("/sbin/init", X_OK) == 0)
		exec_requested("/sbin/init");

	signal(SIGCHLD, reap);
	say("no real init in this ramdisk; idling as pid 1");
	say("the kernel is up - check pstore after the next reset for this log");

	for (;;) {
		/* Nothing to supervise, but pid 1 must not exit: the kernel
		 * panics with "Attempted to kill init" if it does. Sleep in
		 * short slices so a signal is handled promptly. */
		sleep(30);
	}
}
