import { Outlet, NavLink, Link } from "react-router-dom";

import UPHLogoLong from "../../assets/UPHLogoLong.png";

import styles from "./Layout.module.css";

import { useLogin } from "../../authConfig";

import { LoginButton } from "../../components/LoginButton";

const Layout = () => {
    return (
        <div className={styles.layout}>
            <header className={styles.header} role={"banner"}>
                <div className={styles.headerContainer}>
                    <Link to="/" className={styles.headerTitleContainer}>
                        <h3 className={styles.headerTitle}>Chatty for Epic Tip Sheets</h3>
                    </Link>
                    <div className={styles.headerNavLeftMargin}>
                        <div className={styles.logoContainer}>
                            <img src={UPHLogoLong} className={styles.logoImage} aria-hidden="true" />
                        </div>
                    </div>
                    {/* <h4 className={styles.headerRightText}>UnityPoint Health</h4> */}
                    {useLogin && <LoginButton />}
                </div>
            </header>

            <Outlet />
        </div>
    );
};

export default Layout;
